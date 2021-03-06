Life of a HTTP request, as seen by my toy web server
====================================================

When learning a new programming language, I tend to write two things with
it: a language interpreter (usually a FORTH-like language or Brainfuck if
I'm feeling lazy), and a HTTP server.  Sometimes, just as a challenge or a
way to quench my boredom, I do this even though I've been working with a
particular language for some time, as is the case with C.

None of these projects I've written over the years have been as complex as
`Lwan`_ ended up being: most of them were nothing but weekend hacks and were
never able to hold my attention for more than a few dozen hours.

.. _`Lwan`: http://lwan.ws

It's to be expected, then, that I might have a thing or two to say about it. 
In fact, I've been `doing this in homeopathic doses`_ over the almost two years
since I've started the project.  Never actually connected all the dots,
leaving out important details.

.. _`doing this in homeopathic doses`: http://tia.mat.br/blog/html/tags/lwan.html

This article is an attempt to describe, from the perspective of Lwan, the
life of a HTTP request — from the socket being accepted to the response
being sent — and explaining details and reasoning behind the implementation.

Creating the listening socket & accepting connections
-----------------------------------------------------

There's nothing really special here: sockets are either created using the
`standard POSIX stuff`_, or are passed down from `systemd`_.  In either case, TCP
`Fastopen`_ and `Quickack`_ are enabled, in addition to socket lingering.  The
socket is left in its default, blocking mode. The `listen() backlog`_ is the
maximum allowed by the system.

.. _`Fastopen`: http://lwn.net/Articles/508865/
.. _`Quickack`: http://linux.die.net/man/7/tcp#TCP_QUICKACK
.. _`listen() backlog`: http://www.linuxjournal.com/files/linuxjournal.com/linuxjournal/articles/023/2333/2333s2.html
.. _`standard POSIX stuff`: http://linux.die.net/man/2/socket
.. _`systemd`: http://0pointer.net/blog/projects/socket-activation.html

.. code-block:: c

    static int
    _get_backlog_size(void)
    {
    #ifdef SOMAXCONN
        int backlog = SOMAXCONN;
    #else
        int backlog = 128;
    #endif
        FILE *somaxconn;  

        somaxconn = fopen("/proc/sys/net/core/somaxconn", "r");
        if (somaxconn) {
            int tmp;   
            if (fscanf(somaxconn, "%d", &tmp) == 1)
                backlog = tmp;
            fclose(somaxconn);
        }

        return backlog;
    }

It's a blocking file descriptor since the main thread (responsible for
accepting all the sockets and scheduling clients) blocks on a call to
`accept4()`_ instead of something like `Epoll`_.  This `accept()`_ variant is
Linux-only and, among other things, lets one specify flags in sockets
without requiring an additional round trip to the kernel; the only flag that
interests Lwan is ``SOCK_NONBLOCK``.

.. _`Epoll`: http://linux.die.net/man/4/epoll
.. _`accept4()`: http://linux.die.net/man/2/accept4
.. _`accept()`: http://linux.die.net/man/2/accept

.. code-block:: c

    void
    lwan_main_loop(lwan_t *l)
    {
        if (setjmp(cleanup_jmp_buf))
            return;

        signal(SIGINT, _signal_handler);
        
        lwan_status_info("Ready to serve");

        for (;;) {
            int client_fd = accept4(l->main_socket, NULL, NULL,
                                    SOCK_NONBLOCK); 
            if (UNLIKELY(client_fd < 0)) {
                lwan_status_perror("accept");  
                continue;                      
            }

            _schedule_client(l, client_fd);
        }
    }

File descriptor limits are raised to the `maximum allowed by system
settings`_ — at which time, Lwan pre-allocates an array of structures to hold
connection state for all possible file descriptors.

.. _`maximum allowed by system settings`: https://github.com/lpereira/lwan/blob/e660ab753bfc83eb428c5b7de98bd40341589614/common/lwan.c#L415-L432

Scheduling connection
---------------------

In order to multiplex connections, Lwan spawns one thread per logical CPU,
and uses Epoll to determine which socket is ready to be written to or read
from.  Once a connection is scheduled to one of these threads, it stays
there until it is explicitly closed or a timeout occurs.

All threads share the preallocated connection array, and there are no
explicit locks.  The index to this array is the connection file descriptor,
which makes lookup very quick. This exploits the notion that file
descriptors are always allocated from the lowest possible number.

.. code-block:: c

    struct lwan_connection_t_ {
        /* This structure is exactly 32-bytes on x86-64. If it is
         * changed, make sure the scheduler (lwan.c) is updated as
         * well. */
        lwan_connection_flags_t flags;
        unsigned int time_to_die; /* In seconds since DQ epoch */
        coro_t *coro;
        lwan_thread_t *thread;  
        int prev, next;		  /* For death queue */
    };

Since this structure is quite small, this leads to a form of implicit
lock called `false sharing`_, which is solved with a scheduler that is
aware of that problem and groups two connection structures per cache
line.  It's simpler than it sounds:

.. _`false sharing`: https://en.wikipedia.org/wiki/False_sharing
.. code-block:: c

    int thread = ((fd - 1) / 2) % n_threads;

A `round robin scheduler`_ is used on other architectures.

.. _`round robin scheduler`: https://en.wikipedia.org/wiki/Round-robin_scheduling

An interesting curiosity about the connection structure is that it doesn't
store the file descriptor: pointer arithmetic is performed to obtain it, as
the the base address for the connection array is known.

.. code-block:: c

    ALWAYS_INLINE int  
    lwan_connection_get_fd(lwan_connection_t *conn)
    {
        return (int)(ptrdiff_t)(conn - conn->thread->lwan->conns);
    }

After a thread has been chosen by the scheduler, the file descriptor number
is sent to a `Unix domain socket`_ created with `socketpair()`_ to that particular
thread's Epoll. This part used to use `epoll_ctl()`_ directly — which, although
threadsafe, had a problem: `epoll_wait()`_ will never timeout on a socket if
nothing was read from it previously. By writing to that socketpair, Epoll
awakens, the file descriptor is added to it, and that thread's death queue
can handle the timeout by itself.

.. _`Unix domain socket`: https://en.wikipedia.org/wiki/Unix_domain_socket
.. _`socketpair()`: http://linux.die.net/man/2/socketpair
.. _`epoll_ctl()`: http://linux.die.net/man/2/epoll_ctl
.. _`epoll_wait()`: http://linux.die.net/man/2/epoll_wait

The sole purpose of each thread is to react to Epoll events, such as:

* Timeouts (in which case the death queue iterates, potentially
  terminating connections);
* Epoll errors (in which case the thread finishes gracefully);
* Readiness events (can read, can write);
* Connection hung up.

Epoll events are used as signals to create, destroy, resume, and reset
coroutines: there's one for each connection, and they're used both as
lightweight threads and as resource management facilities.

Coroutines
----------

`Coroutines`_ provides a reasonably simple model for asynchronous I/O handling
that’s less convoluted than the dreaded `callback idiom`_ prevalent in C. They
also require a lot less stack space than a thread and their creation is
pretty efficient: essentially just a call to ``malloc()``.

.. _`Coroutines`: https://en.wikipedia.org/wiki/Coroutine
.. _`callback idiom`: https://developer.gnome.org/gio/stable/

.. code-block:: c

    coro_t * 
    coro_new(coro_switcher_t *switcher,
             coro_function_t function,
             void *data)
    {
        coro_t *coro = malloc(sizeof(*coro) + CORO_STACK_MIN);
        if (!coro)
            return NULL;

        coro->switcher = switcher;
        coro->defer = NULL;

        /* coro_reset() is just a few assignments on x86-64 */
        coro_reset(coro, function, data);

    #if !defined(NDEBUG) && defined(USE_VALGRIND)
        char *stack = (char *)(coro + 1);
        coro->vg_stack_id = VALGRIND_STACK_REGISTER(stack,
                                       stack + CORO_STACK_MIN);
    #endif

        return coro;
    }

Request handlers can be written using an API that’s completely synchronous
on the surface but behind the curtains, I/O happens in the background
(client sockets are non-blocking) and control is given to the next coroutine
as commanded by each thread's loop.

Execution resumes where the coroutine left off. This saves a lot of code,
not only making things easier to reason about, but also simplifying resource
management by having a single cleanup point.

To provide a synchronous-looking API, Lwan provides a few wrappers for
common operations, such as `writev()`_ or `sendfile()`_. Unlike the functions
these wrap, they return no error:

.. _`writev()`: http://linux.die.net/man/2/writev
.. _`sendfile()`: http://linux.die.net/man/2/sendfile

* On success, the same return code is returned;
* Recoverable errors (such as ``EINTR``) are handled by trying them again a
  few times before giving up;
* When giving up, or on unrecoverable errors, coroutines are aborted.

.. code-block:: c

    int
    lwan_openat(lwan_request_t *request,
                int dirfd, const char *pathname, int flags)
    { 
        for (int tries = max_failed_tries; tries; tries--) {
            int fd = openat(dirfd, pathname, flags);
            if (LIKELY(fd >= 0)) {
                /*
                 * close() will be called as soon as the
                 * coroutine ends
                 */
                coro_defer(request->conn->coro, CORO_DEFER(close),
                           (void *)(intptr_t)fd);
                return fd;
            }

            switch (errno) {
            case EINTR:
            case EMFILE:
            case ENFILE:
            case ENOMEM:
                coro_yield(request->conn->coro,
                           CONN_CORO_MAY_RESUME);
                break;                                                
            default: 
                return -errno;   
            }
        }

        return -ENFILE;
    } 

When a coroutine is destroyed, user-defined callbacks are executed. These
include callbacks set by the wrapper functions, to close files, free memory,
and perform many other cleanup tasks. This ensures resources are released
regardless if the coroutine ended normally or an unrecoverable error has
been detected.

.. pikchr:: Diagram of main loop plus two coroutines

    ML: box "Main Loop" wid 150% ht 75%  fill 0xd0ece8 
    move
    C1: box "Connection 1" wid 150% ht 75% fill 0xd8ecd0 
    move
    C2: box "Connection 2" wid 150% ht 75% fill 0xe0ecc8 
    down
    move to ML.s
    move
    ML1: box "" width 20% ht 20%   fill 0xd0ece8 
         arrow -> from bottom of ML to top of ML1
    move 120%
    ML2: box "" width 20% ht 40%  fill 0xd0ece8 
         line from bottom of ML1 to top of ML2 dotted
    move
    ML3: box "" width 20% ht 80%  fill 0xd0ece8 
         line from bottom of ML2 to top of ML3 dotted
         line from bottom of ML3 dotted
    move to C1.s
    move 120%
    CL1a: box "" width 20% ht 100% fill 0xd8ecd0 
          line from bottom of C1 to top of CL1a dotted
          arrow "Resume" above -> from ML1.se to CL1a.nw
          arrow "Yield (can resume)" above -> from CL1a.sw to ML2.ne
    move to CL1a.s
    move 180%
    CL1b: box "" width 20% ht 50% fill 0xd8ecd0 
          line from bottom of CL1a to top of CL1b dotted
          arrow "Resume" above -> from ML3.se to CL1b.nw
    move to C2.s
    move 260%
    CL2a: box "" width 20% ht 60% fill 0xe0ecc8 
          line from bottom of C2 to top of CL2a dotted
          arrow "Resume" above -> from ML2.se to CL2a.nw
          arrow "Yield (finished)" above -> from CL2a.sw to ML3.ne
    right
    move to CL2a.s
    move
    Defer: oval "Deferred" italic "callbacks" italic "called" italic
           arrow -> from Defer.w to CL2a.se
    arrow left from CL1b.sw dashed
    line down from CL1b.s dotted


On supported architectures, coroutine context switching is almost as cheap
as a function call.  This is possible because hand-written assembly routines
are used, which only performs the essential register exchange, as mandated
by the `ABI`_.  There is still some work to do in order to speed up this;
tricks used by `libco`_, for instance, might be used in the future to reduce
some of the overhead.

.. _`ABI`: http://www.x86-64.org/documentation/abi.pdf
.. _`libco`: http://byuu.org/programming/libco/

On every other architecture, `swapcontext()`_ is used and this usually incurs
in saving and restoring the signal mask, in addition to swapping every
register (including those not required by the calling convention); this
might change to setjmp() in the future to avoid at least the two system
calls.

.. _`swapcontext()`: http://linux.die.net/man/3/swapcontext

Another use for coroutines in Lwan is inside the Mustache templating engine,
described in more depth below.

Reading requests
----------------

The loop within each I/O thread is `quite crude`_.

.. _`quite crude`: https://github.com/lpereira/lwan/blob/e660ab753bfc83eb428c5b7de98bd40341589614/common/lwan-thread.c#L278-L342

Essentially, a coroutine will only be resumed for reading once per request:
once it yields, Epoll will only be interested in write events. Because of
this, reading a request uses a purpose-built `read() wrapper`_ that tricks the
scheduler to still be interested in read events, unless the request has been
fully received (by ending with the “␍␊␍␊” separator).

.. _`read() wrapper`: https://github.com/lpereira/lwan/blob/e660ab753bfc83eb428c5b7de98bd40341589614/common/lwan-request.c#L459-L514

As soon as the whole request has been received, it is then parsed and acted
upon.

Parsing request
---------------

Request parsing in Lwan is quite efficient: there are no copies, no memory
allocations from the heap.  The buffer is modified in place by slicing and
storing pointers to stuff the server might be interested in.  Parsing of
HTTP request headers is delayed until needed (and they might not be needed).

.. code-block:: c

    struct lwan_request_parse_t_ {
        lwan_value_t buffer;		/* The whole buffer */
        lwan_value_t query_string;	/* Stuff after URLs ? */
        lwan_value_t if_modified_since;	/* If-Modified-Since: */
        lwan_value_t range;		/* Range: */
        lwan_value_t accept_encoding;	/* Accept-Encoding: */
        lwan_value_t fragment;		/* Stuff after URLs # */
        lwan_value_t content_length;	/* Content-Length: */
        lwan_value_t post_data;		/* POST data */
        lwan_value_t content_type;	/* Content-Type: */
        lwan_value_t authorization;	/* Authorization: */
        char connection;		/* k=keep-alive, c=close */
    };
                               
Among other things, one that often receives comments is how headers are
parsed.  Two tricks are involved: avoiding `spilling/filling registers`_ to
compare strings with ``strncmp()``, and applying a heuristic to avoid
reading (and comparing) more than necessary.  Both tricks are intertwined
into a “string prefix switch”:

.. _`spilling/filling registers`: https://en.wikipedia.org/wiki/Register_allocation#Spilling

* Four bytes are read from memory, and are cast to a 32-bit integer pointer;
* That pointer is then dereferenced;
* A standard switch statement is used to perform cheap comparisons on a 32-bit
  integer;
* When a header prefix is matched, a simple heuristic of finding the
  separating colon and space character where they’re supposed to be is used.

  * This might give false positives, although that’s very unlikely in practice.

Once the request has been parsed, it is time to look up what is going to
handle it.

Looking up handler
------------------

A `prefix tree`_ is used to look up handlers. It is a modified trie data
structure that has only eight pointers per node, so that on x86-64, each
node fills one cache line exactly. This is achieved by hashing each
character used to build up a node by taking the 3 least significant bits.

.. _`prefix tree`: https://en.wikipedia.org/wiki/Trie

.. code-block:: c

    struct lwan_trie_node_t_ {
        lwan_trie_node_t *next[8];
        lwan_trie_leaf_t *leaf;
        int ref_count;
    };

The canonical and naïve alternative to the hashed trie is having `256
pointers per node`_, which puts too much virtual memory pressure: the approach
used in Lwan is a good compromise between keeping this pressure low and
implementation complexity.

.. _`256 pointers per node`: https://github.com/lpereira/lwan/blob/b2c9b37e63c7ffedfcbd00c25349ab9501dc4985/lwan-trie.c#L27-L31

Another alternative (which might be considered in the future) is to reduce
the amount of nodes by `coalescing common prefixes`_; this significantly
increases implementation complexity, though, but combined with the string
switch trick, this might yield a good performance boost.

.. _`coalescing common prefixes`: https://en.wikipedia.org/wiki/Trie#Compressing_tries

Yet another technique investigated was to `generate machine code to perform
lookup`_: essentially turning a data structure into executable code. The idea
works but the instruction cache pressure isn't worth the trouble. I'm still
partial to this solution, though, so I might revisit it later: `Varnish`_ does
something remotely similar with VCL and it seems to work, so this deserves a
little bit more research.

.. _`generate machine code to perform lookup`: https://gist.github.com/lpereira/c744c08c74ca600e58ff
.. _`Varnish`: http://www.varnish-cache.org

After a handler is found, a second round of parsing might happen. Each
handler contains a set of flags that signal if headers (which were sliced in
the request parsing stage) should be actually parsed. This include headers
such as Range, Accept-Encoding, If-Modified-Since, and authorization stuff.
Handlers that do not require parsing these headers will not trigger
potentially expensive string crunching.

.. code-block:: c

    typedef enum {
        HANDLER_PARSE_QUERY_STRING = 1<<0,
        HANDLER_PARSE_IF_MODIFIED_SINCE = 1<<1,
        HANDLER_PARSE_RANGE = 1<<2,
        HANDLER_PARSE_ACCEPT_ENCODING = 1<<3,
        HANDLER_PARSE_POST_DATA = 1<<4,
        HANDLER_MUST_AUTHORIZE = 1<<5,
        HANDLER_REMOVE_LEADING_SLASH = 1<<6,

        HANDLER_PARSE_MASK = 1<<0 | 1<<1 | 1<<2 | 1<<3 | 1<<4
    } lwan_handler_flags_t;   

To reduce the amount of boilerplate necessary to declare a handler, there’s
a shortcut that parses almost everything; these are the “request handlers”,
such as the “Hello world handler” example shown below.

Modules, on the other hand, provide much more fine-grained control of how
the request will be handled; an example is the static file serving feature,
also discussed further down.

.. code-block:: c

    static const lwan_module_t serve_files = {
        .name = "serve_files",
        .init = serve_files_init,
        .init_from_hash = serve_files_init_from_hash,
        .shutdown = serve_files_shutdown,
        .handle = serve_files_handle_cb,
        .flags = HANDLER_REMOVE_LEADING_SLASH
            | HANDLER_PARSE_IF_MODIFIED_SINCE
            | HANDLER_PARSE_RANGE
            | HANDLER_PARSE_ACCEPT_ENCODING
    };


Hello world handler
^^^^^^^^^^^^^^^^^^^

The simplest handler possible is a “Hello, World!“. This tests the raw
read-parse-write capacity of Lwan, without requiring more system calls than
absolutely necessary.

.. code-block:: c

    lwan_http_status_t
    hello_world(lwan_request_t *request __attribute__((unused)),
                lwan_response_t *response,
                void *data __attribute__((unused)))
    {
        static const char *hello_world = "Hello, world!";

        response->mime_type = "text/plain";
        strbuf_set_static(response->buffer, hello_world,
                          strlen(hello_world));

        return HTTP_OK;
    }

These simple handlers will use whatever is inside their respective string
buffers (which is an array that grows automatically when needed, with some
bookkeeping attached). In the “Hello, World!” case, however, the string
buffer acts merely as a pointer to some read-only string stored in the text
section; this simplifies the interface a little bit, while avoiding string
copies and unneeded heap allocations.

Chunked encoding and Server-sent events
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Supported also is the `Chunked Encoding`_. Using it is very simple: just set
the response MIME Type, fill the string buffer, and call
``lwan_response_send_chunk()``. From this point on, the response headers will be
sent alongside the first chunk, the string buffer will be cleared, and the
coroutine will yield. To send the next chunk, just fill the string buffer
again and send another chunk, until your handler is complete.

.. _`Chunked Encoding`: https://en.wikipedia.org/wiki/Chunked_transfer_encoding

.. code-block:: c

    lwan_http_status_t
    test_chunked_encoding(lwan_request_t *request, 
                lwan_response_t *response,
                void *data __attribute__((unused)))
    {
        response->mime_type = "text/plain";

        strbuf_printf(response->buffer, "First chunk\n");
        lwan_response_send_chunk(request);

        for (int i = 0; i <= 10; i++) {
            strbuf_printf(response->buffer, "*Chunk #%d*\n", i);
            lwan_response_send_chunk(request);
        }

        strbuf_printf(response->buffer, "Last chunk\n");
        lwan_response_send_chunk(request);

        return HTTP_OK;
    }

The same general idea is used by `Server-sent events`_; however, one uses
``lwan_response_send_event()``, and passes the event name as well.

.. _`Server-sent events`: https://en.wikipedia.org/wiki/Server-sent_events

.. code-block:: c

    lwan_http_status_t
    test_server_sent_event(lwan_request_t *request,
                lwan_response_t *response,
                void *data __attribute__((unused)))
    {
        for (int i = 0; i <= 10; i++) {
            strbuf_printf(response->buffer, "{n: %d}", i);
            lwan_response_send_event(request, "currval");
        }

        return HTTP_OK;
    }


The implementation inside Lwan is as straightforward as it looks: coroutines
saved the day.

File serving module
^^^^^^^^^^^^^^^^^^^

Since files can be served using the ``sendfile()`` system call, the kind of
handlers used by Hello World can't be used: responses are sent using
``writev()`` to send both response headers and contents in one kernel roundtrip.
Because of this, there's a different kind of handler that gives more control
as to how the response is sent: the (for the lack of a better name)
streaming handlers. Streaming handlers are expected to send the whole
response themselves.

To convert a "normal" handler into a streaming handler is simple: just set a
few pointers in the “normal” handler and return. With the exception of
producing error responses automatically — streaming handlers function
exactly the same as a "normal" handler that does not send the response
headers automatically.

.. code-block:: c

    static lwan_http_status_t
    serve_files_handle_cb(lwan_request_t *request,
                          lwan_response_t *response, void *data)
    {
        lwan_http_status_t return_status = HTTP_NOT_FOUND;
        serve_files_priv_t *priv = data;
        struct cache_entry_t *ce;
     
        if (UNLIKELY(!priv)) {
            return_status = HTTP_INTERNAL_ERROR;
            goto fail;
        }

        ce = cache_coro_get_and_ref_entry(priv->cache,
                    request->conn->coro, request->url.value);
        if (LIKELY(ce)) {
            file_cache_entry_t *fce = (file_cache_entry_t *)ce;
            response->mime_type = fce->mime_type;
            response->stream.callback = fce->funcs->serve;
            response->stream.data = ce;
            response->stream.priv = priv;
     
            return HTTP_OK;
        }

    fail:
        response->stream.callback = NULL;
        return return_status;
    }

To avoid having to obtain information about a file for every request, this
information is cached for a few seconds. The caching mechanism itself is
discussed in detail further down.

While caching file information, the file size is considered while picking
the way to serve it.  Files larger than 16KiB are served with ``sendfile()``
to allow zero (or fewer) copy transfers, and smaller files are mapped in
memory using ``mmap()``.

.. code-block:: c

    static const cache_funcs_t *
    _get_funcs(serve_files_priv_t *priv, const char *key,
               char *full_path, struct stat *st)
    {
        char index_html_path_buf[PATH_MAX];   
        char *index_html_path = index_html_path_buf;
        
        if (S_ISDIR(st->st_mode)) {
            /* It is a directory. It might be the root directory
             * (empty key), or something else.  In either case,
             * tack priv->index_html to the path.  */
            if (*key == '\0') {
                index_html_path = (char *)priv->index_html;
            } else {
                /* Redirect /path to /path/. This is to help
                 * cases where there's something like <img
                 * src="../foo.png">, so that actually
                 * /path/../foo.png is served instead of
                 * /path../foo.png.  */
                const char *key_end = rawmemchr(key, '\0');                  
                if (*(key_end - 1) != '/')
                    return &redir_funcs;
        
                if (UNLIKELY(snprintf(index_html_path, PATH_MAX,
                                      "%s%s", key,
                                      priv->index_html) < 0))
                    return NULL;                        
            }

            /* See if it exists. */
            if (fstatat(priv->root.fd, index_html_path, st, 0) < 0) {
                if (UNLIKELY(errno != ENOENT))
                    return NULL;
        
                /* If it doesn't, generate a directory list. */
                return &dirlist_funcs;
            }

            /* If it does, we want its full path. */

            if (UNLIKELY(priv->root.path_len + 1 /* slash */ +
                         strlen(index_html_path) + 1 >= PATH_MAX)) 
                return NULL;

            full_path[priv->root.path_len] = '/';
            strncpy(full_path + priv->root.path_len + 1,
                    index_html_path,
                    PATH_MAX - priv->root.path_len - 1);             
        }

        /* It's not a directory: choose the fastest way to serve the
         * file judging by its size.  */
        if (st->st_size < 16384)
            return &mmap_funcs;

        return &sendfile_funcs;
    }

Small files may also be compressed, unless compressed data ends up being
larger than the original data. Especially if the response header is
considered. Because of this, small files are only compressed if it’s worth
the trouble. The 16KiB threshold has been chosen empirically: larger values
did not yield substantial performance gains compared to using ``sendfile()``.

.. code-block:: c

    static void
    _compress_cached_entry(mmap_cache_data_t *md)
    {
        static const size_t deflated_header_size =
        	sizeof("Content-Encoding: deflate");

        md->compressed.size = compressBound(md->uncompressed.size);

	md->compressed.contents = malloc(md->compressed.size);
        if (UNLIKELY(!md->compressed.contents))
            goto error_zero_out;

	int ret = compress(md->compressed.contents,
	                   &md->compressed.size,
	                   md->uncompressed.contents,
	                   md->uncompressed.size)
        if (UNLIKELY(ret != Z_OK))
            goto error_free_compressed;

	size_t total_size = md->compressed.size
		+ deflated_header_size;
        if (total_size < md->uncompressed.size)
            return;

    error_free_compressed:
        free(md->compressed.contents);
        md->compressed.contents = NULL;
    error_zero_out:
        md->compressed.size = 0;
    }

For directories, the template engine is used to create the listing. The
contents are cached using the same mechanism files are. Templating is
discussed below.

An interesting optimization is that, to obtain the full path, a special
version of `realpath()`_, forked from the GNU libc implementation, is used.
This version uses the `lighter “-at()” variants`_ of system calls that operates
on paths; they do not need to perform path-to-inode conversion for the whole
path, only from a path pointed to by a directory file descriptor. 

.. _`realpath()`: http://linux.die.net/man/3/realpath
.. _`lighter “-at()” variants`: http://lwn.net/Articles/164887/

The file server is a module. It is a simple way to keep per instance state,
such as the file descriptor for the root directory, the directory list
template, and a few other things.

Mustache templating engine
--------------------------

Not all features from `Mustache`_ are implemented: some are pretty much only
practical if using a language that’s more expressive than C. However,
without requiring (too much) boilerplate, a substantial amount of its
specification is implemented, in a pretty efficient way, and suits all Lwan
uses pretty well. (Being performant `might not matter`_, though, but I'm
here to have fun, not solve problems.)

.. _`Mustache`: http://mustache.github.io/
.. _`might not matter`: http://blog.codinghorror.com/the-sad-tragedy-of-micro-optimization-theater/

Not everything is implemented exactly as in the standard, though: that’s
mostly for laziness reasons, but the non-dynamic nature of C would make
certain things needlessly difficult to implement and use, anyway. The
templating engine supports the basic stuff. In no particular order:

* Variables of different types;
* Checking the emptiness of variables;
* Iteration on lists (and any kind of sequences);
* Partials;
* Comments;
* Inverted sections.

Setting the delimiters, triple mustaches (for escaping HTML output),
ampersand to unescape strings — and possibly other things — are not
implemented, but could be implemented with relatively minimal effort. String
escaping is supported by using a special string type and should `conform to
best practices`_.

.. _`conform to best practices`: https://www.owasp.org/index.php/XSS_%28Cross_Site_Scripting%29_Prevention_Cheat_Sheet#RULE_.231_-_HTML_Escape_Before_Inserting_Untrusted_Data_into_HTML_Element_Content

Templates are pre-processed. This pre-processing step uses a state machine
parser to break down its text representation into a series of actions that
can be performed by the engine very efficiently. Actions include things like
“append string”, “append variable”, “start iteration”, and so on.

.. code-block:: c

    typedef enum {
        TPL_ACTION_APPEND,
        TPL_ACTION_APPEND_CHAR,
        TPL_ACTION_VARIABLE,
        TPL_ACTION_LIST_START_ITER,
        TPL_ACTION_LIST_END_ITER,
        TPL_ACTION_IF_VARIABLE_NOT_EMPTY,
        TPL_ACTION_END_IF_VARIABLE_NOT_EMPTY,
        TPL_ACTION_APPLY_TPL,
        TPL_ACTION_LAST
    } lwan_tpl_action_t;
                                    
For instance, a stack of hash tables is used during this pre-processing step
to act as a symbol table; this table can be thrown away as soon as the
pre-processing step is complete, as all variables have been resolved and a
much more efficient value lookup mechanism can be used instead.

Obtaining variables
^^^^^^^^^^^^^^^^^^^

To use the templating mechanism, one should have a structure for each
template. Structures are cheap and provide some welcome compile-time type
checking that wouldn't be possible otherwise.

.. code-block:: c

    typedef struct hello_t {
      char *name;
      int age;
    };

In addition to a structure, due to the lack of introspection in C, an array
of variable descriptors should be declared. A variable descriptor contains a
string representation of a variable name, the offset in bytes of that
variable within the structure, and pointers to functions to test the
emptiness of that kind of variable and to append the variable to the string
buffer; macros help alleviate boilerplate headaches.

.. code-block:: c

    lwan_var_descriptor_t hello_descriptor[] = {
      TPL_VAR_STR(hello_t, name),
      TPL_VAR_INT(hello_t, age),
      TPL_VAR_SENTINEL
    };

    lwan_tpl_t *hello = lwan_tpl_compile("hello.tpl",
                                         hello_descriptor);

A structure containing all the variables can then be supplied by some sort
of database layer, caching layer, or be declared on the spot: compound
literals with designated initializers make this use case pretty
straightforward.

.. code-block:: c

    strbuf_t *rendered = lwan_tpl_render(hello, (hello_t[]) {{
      .name = "World",
      .age = 42
    }});

    /* Do something with `rendered` */

    strbuf_free(rendered);

Appending a variable is then just the matter of calling the
appropriate callback function (conveniently in the descriptor), passing the
base address of that structure plus the byte offset within it.

.. code-block:: c

    static void
    append_var_to_strbuf(lwan_tpl_chunk_t *chunk, void *variables,
                         strbuf_t *buf)
    {
        lwan_var_descriptor_t *descriptor = chunk->data;
        if (LIKELY(descriptor))
            descriptor->append_to_strbuf(buf,
                          (char *)variables + descriptor->offset);
    }



Sequences
^^^^^^^^^

To avoid creating potentially lots of small, temporary objects, for lists
and sequences a coroutine is created and is used as a makeshift generator
function. Another option was to implement iterators using a structure to
hold state plus a few callbacks — I gave up while imagining the amount of
boilerplate necessary. A function is simple to write on the other hand, and
can include initialization, iteration, and cleanup.

.. pikchr:: How sequences are evaluated by the templating engine

    $margin=lineht*2.5

    SEQ0: box "{{#sequence}}"  fill 0xbcd9f3
    line down from SEQ0.s dotted
    SEQ1: box "..." "{{/sequence}}" fill 0xacc9e3
    line down from SEQ1.s dotted
    SEQ2: box "..." "{{/sequence}}" fill 0xacc9e3
    line down from SEQ2.s dotted
    SEQ3: box "{{/sequence}}" fill 0xacc9e3
    arrow down from SEQ3.s
    SEQ4: box  fill 0x9cb9d3

    GEN0: box same with .nw at 1.25*$margin east of 1st box.se  fill 0xc9ace3
    line down from GEN0.s dotted
    GEN1: box same  fill 0xc9ace3
    line down from GEN1.s dotted
    GEN2: box same "Generator" "finished"  fill 0xe3acc9

    arrow from SEQ0.e to GEN0.w
    arrow from GEN0.w to SEQ1.e
    arrow from SEQ1.e to GEN1.w
    arrow from GEN1.w to SEQ2.e
    arrow from SEQ2.e to GEN2.w
    arrow from GEN2.w to SEQ3.e

    text with .s at 0 north of 1st box.n "Template Engine"
    text with .s at 0 north of 6th box.n "Generator Function"

    text with .w at 0 east of 6th box.e "yield 1"
    text with .w at 0 east of 7th box.e "yield 1"
    text with .w at 0 east of 8th box.e "yield 0"

    text with .e at 0 west of 1st box.w "First iteration"
    text with .e at 0 west of 2nd box.w "Recurse"
    text with .e at 0 west of 3rd box.w "Recurse"
    text with .e at 0 west of 4th box.w "Recurse"
    text with .e at 0 west of 5th box.w "Continue" "rendering"

The only user of sequences in templates within Lwan is the file listing
feature in the file serving module. The generator function is pretty
straightforward, and is responsible for opening the directory, obtaining
information for each entry, and then closing the directory. A shorter
version of it is described in the original blog post about `sequences in the
templating engine`_.

.. _`sequences in the templating engine`: http://tia.mat.br/blog/html/2013/09/26/implementing_sequences_in_lwan_template_engine.html

Caching
-------

I’ve used and implemented a few caching infrastructures over the years, and
I believe that the one in Lwan is, so far, the simplest one I’ve used. Most
caches will require items to be created — and then added manually to the
cache. Not only clumsy, but could also lead to race conditions.

The one in Lwan knows how to create and destroy a cache entry: one just asks
the cache to obtain a value for a given key. If it’s not there, the entry is
created and returned. The lifetime of a cache entry is controlled
automatically, and a low priority thread kicks in every now and then to
prune old entries.

.. code-block:: c

    struct cache_t {
        struct {
            struct hash *table;   
            pthread_rwlock_t lock;
        } hash;

        struct {
            struct list_head list;
            pthread_rwlock_t lock;
        } queue;

        struct {
            CreateEntryCallback create_entry;  
            DestroyEntryCallback destroy_entry;
            void *context;
        } cb;

        struct {
            time_t time_to_live;
            clockid_t clock_id;
        } settings;

        unsigned flags;

    #ifndef NDEBUG
        struct {
            unsigned hits;   
            unsigned misses; 
            unsigned evicted;
        } stats;
    #endif
    };

Unlike most caches, the one in Lwan isn’t limited by size: items stay in the
cache for a predetermined amount of time.

Cache entries are reference-counted, and they’re not automatically reaped if
something is holding on a reference: these items are marked as floating when
this happens, and the last one to give up the reference will also destroy
the entry.

.. code-block:: c

    struct cache_entry_t {
      struct list_node entries;
      char *key;
      unsigned refs;
      unsigned flags;
      struct timespec time_to_die;
    };

    struct file_cache_entry_t_ {
        struct cache_entry_t base;

        struct {
            char string[31];
            time_t integer;
        } last_modified;

        const char *mime_type;
        const cache_funcs_t *funcs;
    };

When used within a coroutine, two things can happen: ➀ the coroutine might
yield if the cache lock were to become contended and ➁ automatically
releasing a reference when a coroutine is destroyed.

In addition to floating entries, there are also temporary entries. The cache
uses read-write locks, but most of the time, locks are only obtained using
the “trylock” primitive: if a lock can’t be obtained for a reason, Lwan
tries to move on to something else. This could be attending to another
request (by yielding the coroutine), or merely returning an off-the-books
entry that will be destroyed as soon as its sole user releases its
reference. The difference to floating entries is merely an implementation
detail, so that an atomic decrement (and its accompanying memory barrier)
isn’t used.

The cache tries to avoid keeping the locks locked. As an example, while an
item is being created, no locks are held. This can, of course, lead to
multiple entries being created concurrently, but if caching would be useful
anyway, having a few temporary entries lying around isn’t a problem, as at
least one will be cached for future access.

As nice as the cache subsystem ended up being, there is a lot of room for
improvement.  Reducing the amount of concurrent reference counting is high
on the list.  Reducing the latency is also in consideration.  Making HTTP
responses cacheable without special code in the handler is there as well.

Keep-alive connections, death queue
-----------------------------------

Connection lifetime is managed by a per-thread queue.

Each time a connection is scheduled to a certain thread, it is pushed to the
queue, and a time to die is set. When there are connections in this queue,
Epoll will timeout every second to iterate through it and kill connections
when their time has come. Timeouts are infinite when the queue is empty, to
avoid waking the process unnecessarily. Every time a coroutine is resumed,
the time to die is updated, and the connection is pushed to the end of the
queue.

Each death queue has its own epoch, which starts at zero and increments at
every timeout. Whenever the last connection is removed from a queue, the
epoch restarts. Keeping the epoch a small number will help shave a few bytes
from each connection in the future.

.. code-block:: c

    struct death_queue_t {
        lwan_connection_t *conns;
        lwan_connection_t head;
        unsigned time;
        unsigned short keep_alive_timeout;
    };
                
The same timeout value is used for keep-alive connections and coroutines.
This ensures coroutines will not linger indefinitely when not performing any
kind of work.

The death queue is so important that almost a third of the connection
structure is dedicated to its existence. Three integers keep state for the
death queue: the time to die (as an unsigned int), and two integers as
pointers to a doubly linked list.

Integers were used instead of pointers in order to save memory. This was
possible since in reality they are indices to the connection array. A doubly
linked list was also chosen since removing a connection from the middle of
the queue should be efficient, as it is done very frequently to move the
entry to the end. The list is also circular, in order to avoid branching to
handle empty queue cases. Maintaining the queue inline with the connection
structures help reducing cache pressure.

.. code-block:: c

    static inline int _death_queue_node_to_idx(
    		struct death_queue_t *dq, lwan_connection_t *conn)
    {
        return (conn == &dq->head) ?
        	-1 : (int)(ptrdiff_t)(conn - dq->conns);
    }

    static inline lwan_connection_t *_death_queue_idx_to_node(
    		struct death_queue_t *dq, int idx)
    {
        return (idx < 0) ? &dq->head : &dq->conns[idx];
    }
     
    static void _death_queue_insert(struct death_queue_t *dq,
        lwan_connection_t *new_node)                         
    {
        new_node->next = -1;
        new_node->prev = dq->head.prev;   
        lwan_connection_t *prev = _death_queue_idx_to_node(dq,
                                               dq->head.prev);
        dq->head.prev = prev->next = _death_queue_node_to_idx(dq,
                                                       new_node);
    }

    static void _death_queue_remove(
    		struct death_queue_t *dq, lwan_connection_t *node)
    { 
        lwan_connection_t *prev = _death_queue_idx_to_node(dq,
                                                  node->prev);
        lwan_connection_t *next = _death_queue_idx_to_node(dq,
                                                  node->next);
        next->prev = node->prev;
        prev->next = node->next;
    }


Closing words
-------------

That's pretty much it: when a response has been sent, the connection can
either be closed, or a new request can be serviced in the same connection.
Repeat ad infinitum and there's the `HTTP server`_.

If you've made this far, I invite you to take a look at the `full source code`_.
There are things that were not mentioned in this article. It's also a young
Free Software project with no entry barrier: just fork and issue a pull
request.

.. _`HTTP server`: http://lwan.ws
.. _`full source code`: https://github.com/lpereira/lwan

.. author:: default
.. categories:: none
.. tags:: lwan, programming, C, _featured
.. comments::

