Asynchronous I/O in C with Coroutines
=====================================

Writing asynchronous I/O code in C is kind of tedious, and often leads to a
callback hell. But it doesn’t have to be this way; if you have a main loop,
it’s quite simple to use `coroutines`_ and write code in a soothing, old
school, synchronous way.

.. image:: http://i.imgur.com/dHCqj.jpg
    :alt: yodawg


Under POSIX, it’s also quite easy to implement coroutines, via the use of the
stuff contained in the `ucontext.h`_ header. Unfortunately deprecated in
favor of threads, the functions and structures found in this header are one
of the unpopular gems in the POSIX C library.


Coroutines in lwan, my toy web server
:::::::::::::::::::::::::::::::::::::

In `lwan`_, there are ``n + 1`` worker threads, where ``n`` is the number of
logical CPUs. One thread is the *acceptor* thread, which accepts connections,
and gives control to the other ``n`` threads, which in turn do all the work
of receiving a request, parsing, and delivering the response.

Each of these worker threads can multiplex thousands of connections by
polling on events: so, for each worker thread, only one request can be
handled at a time. And, if one blocking operation (say, write to a socket)
would block, all other requests would wait for a response.

By *yielding* the coroutine at the right moments, lwan blocks only on calls
to `epoll(4)`_. Whenever the socket can be written again, that coroutine is
resumed. The request handler function does not know what happened.


Implementing coroutines using ucontext
::::::::::::::::::::::::::::::::::::::

As said earlier, POSIX offers some infrastructure that can be used to
implement coroutines or more powerful concepts, like `call/cc`_. However,
they’re quite tricky to use, so it’s often a good idea to offer a thin
wrapper on top of them. The API used in lwan is the following (implementation
details omitted for brevity):

.. code-block:: c

    coro_t *coro_new(coro_function_t function, void *data);
    void coro_free(coro_t *coro);
    int coro_resume(coro_t *coro);
    void coro_yield(coro_t *coro, int value);

Coroutine allocation
::::::::::::::::::::

A coroutine is pretty much a simple data structure; the real implementation
has more fields, but they’re implementation details:

.. code-block:: c

    struct coro_t_ {
        coro_function_t function;
        void *data;

        ucontext_t context;
        int yield_value;

        char stack[1];
    };

To allocate one, just allocate space for ``sizeof(coro_t_) + stack_size``,
initialize the variables, and call ``getcontext(&coro->context)``. (These
context-swapping functions are weirdly-named in my opinion: ``getcontext``
actually *saves* the current context into the variable pointed to by its sole
parameter.)

After that, one just need to set up the context so that it points to the
newly-allocated stack:

.. code-block:: c

    coro->context.uc_stack.ss_sp = coro->stack;
    coro->context.uc_stack.ss_size = stack_size;
    coro->context.uc_stack.ss_flags = 0;
    coro->context.uc_link = NULL;

And then call ``makecontext()`` so that the coroutine entry point can be
called when resuming the coroutine. (Another weirdly-named function. No
wonder why this thing is quite unpopular.) This function takes a variable
number of parameters, each one being a 32-bit integer value. I don’t know why
a ``void *`` wasn’t used instead – so, on 64-bit, I use an union to break a
pointer into two 32-bit components:

.. code-block:: c

    union ptr_splitter {
        void *ptr;
        uint32_t part[2];
    };

That’s it to allocate a coroutine.


Freeing a coroutine
:::::::::::::::::::

Just free the coroutine’s ``coro_t`` structure. Lwan’s implementation does
run the deferred statements at this moment.


Resuming a coroutine
::::::::::::::::::::

Resuming a coroutine pretty simple: one has to save the current context, swap
the current context with the coroutine context, and when the coroutine
yields, return the contexts where they were.


Yielding from a coroutine
:::::::::::::::::::::::::

To yield from a coroutine, just save ``value`` into ``coro_t``’s
``yield_value`` field, and make a call to ``swapcontext()``, swapping the
current coroutine stack with the context that was active when the coroutine
was resumed (which happens to be the routine that resumes a coroutine – which
now cleans up and return to whoever called it, most probably the main loop).
``value`` is now available to whoever called ``coro_resume()`` and is used in
lwan to determine if a coroutine should be resumed.


Using the coroutines
::::::::::::::::::::

From the user perspective, it’s just like calling some blocking function:

.. code-block:: c

    lwan_sendfile(request->socket, file_fd, 0, total_bytes);

Behind the scenes, ``lwan_sendfile`` is actually doing this (error handling
omitted for brevity):

.. code-block:: c

    while (sent_bytes < total_bytes) {
        read_bytes = read(file_fd, buffer, buffer_size);
        sent_bytes += read_bytes;
        write(socket_fd, buffer, read_bytes);

        coro_yield(coro, 1);
    }


(Of course, if available, `sendfile(2)`_ is used instead in a similar
fashion, but this better illustrates the point.)

Whenever the coroutine yields, it goes back to the main loop, which is now
free to resume another coroutine. Ideally, one could yield to be resumed on a
certain condition (instead of assuming that the condition is just “the socket
is ready to be written to”), but this isn’t possible in the current
implementation.

For implementation simplicity, the same timer code that is used for keep-
alive connections is used for coroutines, so that they don’t linger
indefinitely.


Implementation details
::::::::::::::::::::::

-   On 64-bit, hand-tuned assembly versions of ``ucontext`` routines are
    used. These routines avoid saving and restoring the signal mask (avoiding
    two roundtrips to the kernel), and does not save the floating point
    registers.
-   Also, on 64-bit, resuming a coroutine is orders of magnitude faster,
    since not everything is copied when switching contexts.
-   Swapping stacks makes tools like `Valgrind`_ get pretty crazy. Lwan’s
    implementation uses Valgrind-provided macros that marks the newly-
    allocated blocks (from the heap) as stacks.
-   The real implementation has a ``coro_switcher_t`` data structure.
    This structure is used to both avoid race conditions when swapping
    coroutines in different threads, but also to maintain coroutine state
    from different threads.

There are other details that were ommitted from this post. Lwan’s source code
is small enough it can digested easily, and if you’re not sleeping already,
check it out.


Closing notes
:::::::::::::

Although not as performant as the traditional way of using callbacks
(resuming and yielding from coroutines are a little bit more expensive than
calling a function), coroutines brings a lot of simplicity when writing
asynchronous code.

The example shown here might not be expressive, but imagine an application
fetching data from a key-value store from another machine: there might be
dozens of calls to the database to build a web page, which would be pretty
difficult to handle if there were dozen callbacks. With a synchronous style,
that would be a lot easier to write and maintain.

One could argue that the same thing could be done in threads. But creating
more threads than there are processors will often hurt performance (for
various reasons) in noticeable ways. Also, coroutines are cheaper on the
memory requirements: in Lwan, they sport 16KiB of stack space and it takes a
little bit more than a ``malloc()`` to set them up.

I believe we should stop using callbacks for asynchronous I/O and use things
like this. Even if ``ucontext.h`` is deprecated from POSIX, the functions a
fairly trivial to write (even in assembly language) – actually, encouraged,
given that ``swapcontext()`` and ``getcontext()`` makes often unnecessary
system calls.

.. _coroutines: https://en.wikipedia.org/wiki/Coroutine
.. _ucontext.h: https://en.wikipedia.org/wiki/Setcontext
.. _lwan: http://github.com/lpereira/lwan
.. _epoll(4): http://linux.die.net/man/4/epoll
.. _call/cc: https://en.wikipedia.org/wiki/Call-with-current-continuation
.. _sendfile(2): http://linux.die.net/man/2/sendfile
.. _Valgrind: http://valgrind.org/



.. author:: default
.. categories:: none
.. tags:: trick,lwan,programming,C
.. comments::