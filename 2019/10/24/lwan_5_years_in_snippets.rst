Lwan: 5 years in snippets
=========================

.. author:: default
.. categories:: programming
.. tags:: lwan
.. comments::

Around five years ago, I wrote a blog post that went though the
life-cycle of a HTTP request, as seen by my toy web server, Lwan. It was
a surprisingly popular article, not only raising visibility for my toy
project, but also generating some discussions on link aggregator web
sites and personal emails. (`You can read the blog
post <https://tia.mat.br/posts/2014/10/06/life_of_a_http_request.html>`__
if you haven’t already or need some refreshing.)

While I haven’t been working on it with the vigor I had in its first few
years, a few things changed nonetheless; this article is a follow-up
article on that. (Which I recommend reading, as out-of-date as it is:
most things in the server didn’t change.)

Items in this article aren’t in any particular order; it’s just a
collection of changes that happened since the original article was
written. Not everything is mentioned here, of course, but should give an
idea of the kind of work that kept me busy during some lazy Sundays.

Main Loop Changes
=================

The main loop was designed to either wait indefinitely, or time out
every second, depending on how many file descriptors are being watched
by a worker thread. This made it quite hard to implement something that
was required for some use cases I wanted to use Lwan for: the ability
for a request handler to pause the execution for a specified amount of
time.

Request handlers, being executed in a coroutine, are subject to a
cooperative scheduler, so they can’t just use system calls like
``usleep()``; instead, many changes in the main loop were performed to
support timers, paving the way for other potential enhancements in the
future (e.g.  non-client file descriptor watching, for instance).

Each thread has a timer wheel data structure, which can be thought of a
efficient priority queue that has the sole purpose of maintaining a set
of timers. Usually, I’d just implement one from the scratch; however,
while looking for implementations for inspiration, I ended up stumbling
over
`timeout.c <https://25thandclement.com/~william/projects/timeout.c.html>`__,
which has a decent API and has seen some abuse in programs like TOR. I
performed a few minor tweaks when importing the library to the tree, and
am now using it to control how much time ``epoll_wait()`` will block
waiting for file descriptor events; and, if none were returned, timers
are processed, and coroutines are marked as “ready to be resumed”.

.. code:: c

   static void *thread_io_loop(void *data)
   {
       /* This is the entry point for the worker threads.  The infinite loop
        * below is the meat of event handling in Lwan.  Everything passes
        * through this loop.  */

       /* (Initialization omitted for brevity.) */

       for (;;) {
           /* Turning the timer wheel will also process pending timers,
            * including the one that moves the timeout queue and updates the
            * date/time cache.  It then returns how much time epoll_wait()
            * has to wait in ms. */
           int timeout = turn_timer_wheel(&dq, t, epoll_fd);
           int n_fds = epoll_wait(epoll_fd, events, max_events, timeout);

       /* To quit Lwan, all epoll file descriptors are closed, and the
        * threads are nudged.  This wakes up epoll_wait(), and the next
        * time it's called, it's going to probably return EBADF. */
           if (UNLIKELY(n_fds < 0)) {
               if (errno == EBADF || errno == EINVAL)
                   break;
               continue;
           }

           for (struct epoll_event *event = events; n_fds--; event++) {
               if (UNLIKELY(!event->data.ptr)) {
                   accept_nudge(read_pipe_fd, t, lwan->conns, &dq, &switcher,
                                epoll_fd);
                   continue;
               }

               struct lwan_connection *conn = event->data.ptr;

               if (UNLIKELY(event->events & (EPOLLRDHUP | EPOLLHUP))) {
                   death_queue_kill(&dq, conn);
                   continue;
               }

               resume_coro(&dq, conn, epoll_fd);
               death_queue_move_to_last(&dq, conn);
           }
       }

       /* (Cleanup omitted for brevity.) */

       return NULL;
   }

While coroutines are sleeping, their file descriptor is still tracked by
epoll, in case the connection is dropped by the peer. Awaking a
coroutine is essentially just the matter of listening to the events that
it was listening before it went on to sleep. (At the moment, this means
both read and write events, as it was easier to implement – although
different on kqueue systems, where reading/writing are not events but
filters, which can’t be combined in a single throw.)

A coroutine expresses their desire to sleep to the main loop by yielding
with a special value. (Previously, it could only say ‘yield, but resume
me later’ or ‘yield, but destroy me whenever you can’; this changed in
the recent months.)

With all the infrastructure work, the API entry point to suspend the
corroutine for an specified amount of time becomes trivial:

.. code:: c

   static void remove_sleep(void *data1, void *data2)
   {
       struct timeouts *wheel = data1;
       struct timeout *timeout = data2;
       struct lwan_request *request =
           container_of(timeout, struct lwan_request, timeout);

       if (request->conn->flags & CONN_SUSPENDED_TIMER)
           timeouts_del(wheel, timeout);

       request->conn->flags &= ~CONN_HAS_REMOVE_SLEEP_DEFER;
   }

   void lwan_request_sleep(struct lwan_request *request, uint64_t ms)
   {
       struct lwan_connection *conn = request->conn;
       struct timeouts *wheel = conn->thread->wheel;

       request->timeout = (struct timeout) {};
       timeouts_add(wheel, &request->timeout, ms);

       if (!(conn->flags & CONN_HAS_REMOVE_SLEEP_DEFER)) {
           coro_defer2(conn->coro, remove_sleep, wheel, &request->timeout);
           conn->flags |= CONN_HAS_REMOVE_SLEEP_DEFER;
       }

       /* The meaning of CONN_CORO_SUSPEND_TIMER will become clear in the next
        * section. */
       coro_yield(conn->coro, CONN_CORO_SUSPEND_TIMER);
   }

(The next section explains a little bit more of how the infrastructure
works.)

Due to the nature of the hashed timer wheel, when ``epoll_wait()`` wakes
up every second to update the time cache and process the timeout queue,
it may wake up a few more times with intervals smaller than 1 second. In
practice, this ends up being slightly more accurate, as the system’s
monotonic clock source is used to offset any time between
``epoll_wait()`` invocations, avoiding timer drift. (It’s slightly more
accurate because the coarse monotonic clock is used if available, and
the timeout in ``epoll_wait()`` uses the fine-grained variant instead.
Maybe a ``EPOLL_COARSE_CLOCKSOURCE`` flag to ``epoll_create1()`` would
be worthwhile investigating?)

Changing Connection Coroutine Yield Values
==========================================

One of the trickiest bits in Lwan was its main loop and how it
determined which epoll events mask to choose depending on the connection
state. It was often the case that a connection would stall indefinitely
for no reason, which was often caused when it had declared that it
wanted to be resumed only when the socket was ready to read, when it
wanted to write instead. The code responsible for this was very brittle
and didn’t make much sense, although it worked most of the time. It
really needed a big overhaul (which turned out to not be big, line-count
wise.)

The main idea behind the changes here was to add new values that
coroutines could use to inform the scheduler what it was interested in:
reading from the socket, writing to the socket, sleeping, this sort of
stuff. This is mostly hidden from most of the code, though, being
necessary to be aware of only by the I/O wrappers (a coroutine now
yields automatically, for instance, if ``lwan_read()`` detects that
read() failed with a ``EAGAIN`` ``errno``, to change the coroutine
intent to be resumed whenever the socket can be read again).

The nice thing about this change is that it changed a bunch of branches
and operations with straightforward table lookups. In the past few
years, I’ve been moving towards using lookup tables a whole lot more;
it’s sometimes difficult to express a rat’s nest of branches in a way
that’s efficient to look it up on a table, but it’s a satisfying feeling
when all that crud is gone and all you’re left with are a few array
accesses.

Contrast the new, shiny, table-based approach:

.. code:: c

   static ALWAYS_INLINE uint32_t
   conn_flags_to_epoll_events(enum lwan_connection_flags flags)
   {
       static const uint32_t map[CONN_EVENTS_MASK + 1] = {
           [0 /* Suspended by timer */] = EPOLLRDHUP,
           [CONN_EVENTS_WRITE] = EPOLLOUT | EPOLLRDHUP,
           [CONN_EVENTS_READ] = EPOLLIN | EPOLLRDHUP,
           [CONN_EVENTS_READ_WRITE] = EPOLLIN | EPOLLOUT | EPOLLRDHUP,
       };

       return map[flags & CONN_EVENTS_MASK];
   }

   #if defined(__linux__)
   # define CONN_EVENTS_RESUME_TIMER CONN_EVENTS_READ_WRITE
   #else
   /* Kqueue doesn't like when you filter on both read and write, so
    * wait only on write when resuming a coro suspended by a timer.
    * The I/O wrappers should yield if trying to read without anything
    * in the buffer, changing the filter to only read, so this is OK. */
   # define CONN_EVENTS_RESUME_TIMER CONN_EVENTS_WRITE
   #endif

   static void update_epoll_flags(int fd,
                                  struct lwan_connection *conn,
                                  int epoll_fd,
                                  enum lwan_connection_coro_yield yield_result)
   {
       static const enum lwan_connection_flags or_mask[CONN_CORO_MAX] = {
           [CONN_CORO_YIELD] = 0,
           [CONN_CORO_WANT_READ_WRITE] = CONN_EVENTS_READ_WRITE,
           [CONN_CORO_WANT_READ] = CONN_EVENTS_READ,
           [CONN_CORO_WANT_WRITE] = CONN_EVENTS_WRITE,

           /* While the coro is suspended, we're not interested in either EPOLLIN
            * or EPOLLOUT events.  We still want to track this fd in epoll, though,
            * so unset both so that only EPOLLRDHUP (plus the implicitly-set ones)
            * are set. */
           [CONN_CORO_SUSPEND_TIMER] = CONN_SUSPENDED_TIMER,

           /* Either EPOLLIN or EPOLLOUT have to be set here.  There's no need to
            * know which event, because they were both cleared when the coro was
            * suspended. So set both flags here. This works because EPOLLET isn't
            * used. */
           [CONN_CORO_RESUME_TIMER] = CONN_EVENTS_RESUME_TIMER,
       };
       static const enum lwan_connection_flags and_mask[CONN_CORO_MAX] = {
           [CONN_CORO_YIELD] = ~0,
           [CONN_CORO_WANT_READ_WRITE] = ~0,
           [CONN_CORO_WANT_READ] = ~CONN_EVENTS_WRITE,
           [CONN_CORO_WANT_WRITE] = ~CONN_EVENTS_READ,
           [CONN_CORO_SUSPEND_TIMER] = ~CONN_EVENTS_READ_WRITE,
           [CONN_CORO_RESUME_TIMER] = ~CONN_SUSPENDED_TIMER,
       };
       enum lwan_connection_flags prev_flags = conn->flags;

       conn->flags |= or_mask[yield_result];
       conn->flags &= and_mask[yield_result];

       if (conn->flags == prev_flags)
           return;

       struct epoll_event event = {
           .events = conn_flags_to_epoll_events(conn->flags),
           .data.ptr = conn,
       };

       if (UNLIKELY(epoll_ctl(epoll_fd, EPOLL_CTL_MOD, fd, &event) < 0))
           lwan_status_perror("epoll_ctl");
   }

With the crusty, buggy, old approach that only worked by chance (and was
the source of a lot of headache):

.. code:: c

   static void update_epoll_flags(struct death_queue *dq,
                                  struct lwan_connection *conn,
                                  int epoll_fd,
                                  enum lwan_connection_coro_yield yield_result)
   {
       uint32_t events = 0;
       bool write_events;

       if (UNLIKELY(conn->flags & CONN_RESUMED_FROM_TIMER)) {
           conn->flags &= ~(CONN_RESUMED_FROM_TIMER | CONN_WRITE_EVENTS);
           write_events = false;
       } else if (UNLIKELY(conn->flags & CONN_SUSPENDED_BY_TIMER)) {
           /* CONN_WRITE_EVENTS shouldn't be flipped in this case. */
           events = EPOLLERR | EPOLLRDHUP;
       } else if (conn->flags & CONN_MUST_READ) {
           write_events = true;
       } else {
           bool should_resume_coro = (yield_result == CONN_CORO_MAY_RESUME);

           if (should_resume_coro)
               conn->flags |= CONN_SHOULD_RESUME_CORO;
           else
               conn->flags &= ~CONN_SHOULD_RESUME_CORO;

           write_events = (conn->flags & CONN_WRITE_EVENTS);
           if (should_resume_coro == write_events)
               return;
       }

       if (LIKELY(!events)) {
           events = events_by_write_flag[write_events];
           conn->flags ^= CONN_WRITE_EVENTS;
       }

       struct epoll_event event = {.events = events, .data.ptr = conn};

       int fd = lwan_connection_get_fd(dq->lwan, conn);
       if (UNLIKELY(epoll_ctl(epoll_fd, EPOLL_CTL_MOD, fd, &event) < 0))
           lwan_status_perror("epoll_ctl");
   }

Changes in parsers
==================

RFC822 (Date headers)
---------------------

Unhappy with the performance of ``strptime()``, I came up with a parser
that fits the theme of the rest of the HTTP parser in Lwan quite well:
by using string switch statements, the `new time parser is faster by a
around 12x when compared with the generic one from the C
library <https://gist.github.com/lpereira/4e09f5a038b740d61860488679427c4e>`__.

.. code:: c

   int lwan_parse_rfc_time(const char in[static 30], time_t *out)
   {
       /* This function is used instead of strptime() because locale
        * information can affect the parsing.  Instead of defining
        * the locale to "C", use hardcoded constants. */
       struct tm tm;
       const char *str = in;

       STRING_SWITCH(str) {
       case STR4_INT('S','u','n',','): tm.tm_wday = 0; break;
       case STR4_INT('M','o','n',','): tm.tm_wday = 1; break;
       case STR4_INT('T','u','e',','): tm.tm_wday = 2; break;
       case STR4_INT('W','e','d',','): tm.tm_wday = 3; break;
       case STR4_INT('T','h','u',','): tm.tm_wday = 4; break;
       case STR4_INT('F','r','i',','): tm.tm_wday = 5; break;
       case STR4_INT('S','a','t',','): tm.tm_wday = 6; break;
       default: return -EINVAL;
       }
       str += 5;

       tm.tm_mday = parse_2_digit_num(str, ' ', 1, 31);
       if (UNLIKELY(tm.tm_mday < 0))
           return -EINVAL;
       str += 3;

       STRING_SWITCH(str) {
       case STR4_INT('J','a','n',' '): tm.tm_mon = 0; break;
       case STR4_INT('F','e','b',' '): tm.tm_mon = 1; break;
       case STR4_INT('M','a','r',' '): tm.tm_mon = 2; break;
       case STR4_INT('A','p','r',' '): tm.tm_mon = 3; break;
       case STR4_INT('M','a','y',' '): tm.tm_mon = 4; break;
       case STR4_INT('J','u','n',' '): tm.tm_mon = 5; break;
       case STR4_INT('J','u','l',' '): tm.tm_mon = 6; break;
       case STR4_INT('A','u','g',' '): tm.tm_mon = 7; break;
       case STR4_INT('S','e','p',' '): tm.tm_mon = 8; break;
       case STR4_INT('O','c','t',' '): tm.tm_mon = 9; break;
       case STR4_INT('N','o','v',' '): tm.tm_mon = 10; break;
       case STR4_INT('D','e','c',' '): tm.tm_mon = 11; break;
       default: return -EINVAL;
       }
       str += 4;

       tm.tm_year = parse_int(strndupa(str, 4), -1);
       if (UNLIKELY(tm.tm_year < 0))
           return -EINVAL;
       tm.tm_year -= 1900;
       if (UNLIKELY(tm.tm_year < 0 || tm.tm_year > 1000))
           return -EINVAL;
       str += 5;

       tm.tm_hour = parse_2_digit_num(str, ':', 0, 23);
       str += 3;
       tm.tm_min = parse_2_digit_num(str, ':', 0, 59);
       str += 3;
       tm.tm_sec = parse_2_digit_num(str, ' ', 0, 59);
       str += 3;

       STRING_SWITCH(str) {
       case STR4_INT('G','M','T','\0'):
           tm.tm_isdst = -1;

           *out = timegm(&tm);

           if (UNLIKELY(*out == (time_t)-1))
               return -EINVAL;

           return 0;

       default:
           return -EINVAL;
       }
   }

`Wojciech Muła <http://0x80.pl/>`__ wrote a better version using `SIMD
instructions <https://github.com/WojciechMula/toys/tree/master/parse_rfc_date>`__
after they learned about this routine; it was then improved by `Kendall
Willets <https://twitter.com/kendallwillets>`__ to use a different
technique (a perfect hash table). Both are faster than the version used
in Lwan, but I decided to keep my version because not only it is fast
enough, it’s also more maintainable; it also serves as a pretty good
example for the `string switch
trick <https://tia.mat.br/posts/2018/02/01/more_on_string_switch_in_c.html>`__.

(As a complement to this change, the function that converts a time_t
into the same string that ``lwan_parse_rfc_time()`` parses has been
written as well, and it’s as efficient as I could make it, even going to
the effort of reducing the number of divisions to convert integers into
strings from 6 to just 1.)

Configuration parser & Template parser
--------------------------------------

Both the configuration file parser and the template parser were written
without paying attention to anything related to compiler theory; just an
ad-hoc parser without a proper lexer, looking at a line at a time. Both
had a lot of workarounds and were generally hard to extend and debug.
They needed to be rewritten, but I really didn’t want to use a parser
generator (I really don’t like them).

For both of these parsers, used the same technique in the `JSON parser I
wrote for the Zephyr
project <https://tia.mat.br/posts/2017/03/01/parsing_json.html>`__: a
state machine (where the variable that holds the state actually holds a
pointer to a function that handles that state), and a ring buffer. I
really like this technique, as it’s often easier to grasp than many of
the parser generators out there. (There’s the added benefit that no new
build dependencies or build system changes is required.)

Here’s how one of these functions might look; this one doesn’t use the
ring buffer, only consumes bytes from the input:

.. code:: c

   static void *lex_comment(struct lexer *lexer)
   {
       /* lex_config() returns 'lex_comment' when 'next(lexer)' returns '#' */
       while (iscomment(next(lexer)))
           ;

       /* Current character isn't a comment, back it up: next state should be
        * able to read it and determine which state is going to process the
        * next token. */
       backup(lexer);

       /* lex_config() handles the main state */
       return lex_config;
   }

And here’s how the function that handles the “get me a new token”
function that the parser calls looks:

.. code:: c

   static bool lex_next(struct lexer *lexer, struct lexeme **lexeme)
   {
       /* To end the state machine, a state-handling function returns NULL,
        * ending this loop.  */

       while (lexer->state) {
           /* If a state handling function emits one or more tokens, for as
            * long as lex_next() is called, instead of calling the function to
            * handle the current state, items from the ring buffer are popped
            * instead.  */
           if (lexeme_buffer_consume(&lexer->buffer, lexeme))
               return true;
    
           /* Run the state machine for the current state, and update it if
            * necessary.  */
           lexer->state = lexer->state(lexer);
       }
    
       /* Exhaust the ring buffer until there's nothing left. */
       return lexeme_buffer_consume(&lexer->buffer, lexeme);
   }

The configuration file parser got a few nice features, like the ability
to expand environment variables (or use a default value provided in the
configuration file), multiline strings, and other minor changes and
bugfixes that would be too complicated to implement in the previous
bespoke one-line-at-a-time thing that was in place.

The template parser also got significantly more robust, handling some
corner cases that were just impossible before. (No new significant
changes have been performed in the runtime portion, though, although a
few tweaks here and there were made over the years.) Unrelated to the
parser changes, a template can be “compiled” with an option that won’t
allocate and copy a new string for each text fragment, but use text
that’s in memory somewhere; this is useful for things such as the file
serving module or the default response generator, when a template has
not been supplied by the user in the configuration file, where
``strbuf`` structs used by the template mechanism can just point into
somewhere in ``rodata``.

Readahead & Madvise
===================

The Linux system call ``sendfile()`` doesn’t take flags like the FreeBSD
variant, so it’s impossible to tell it not to block if data isn’t in the
core yet. The best one can do, as far as I can tell, is to make sure
that the data is already there when it is invoked. That’s why Lwan now
has a low-priority thread (which has also low-priority I/O thread on
Linux) that will call ``readahead()`` on file chunks as they’re being
served.

This thread takes commands through a pipe, where only the write side is
non-blocking. (Failure to write to that socket isn’t an issue, as this
is merely an optimization, so this is one of the rare cases in Lwan
where a syscall error isn’t handled.) As commands are received, that
thread is free to block (or, more specifically, wait for as much as
necessary) to load the contents into core, so that hopefully the thread
calling ``sendfile()`` won’t block. This optimization was only possible
because the cache in the file serving module keeps the files open.

For the cases where files are served with a memory-mapped blob of
memory, the problems can be even more apparent; there’s no way to say
“dereference this memory but please don’t block” in any of the supported
platforms. Your only bet is to memory map it, give a hint to the OS to
pre-fault the pages, and lock it in memory. But the ``madvise()`` and
``mlock()`` combo used for this will eventually encounter similar
problems as with the ``readahead()`` syscall, in which while they might
not exactly block, they’ll take some time to process whatever they need
to process. So the same thread that performs ``readahead()`` will also
try to bring stuff to the core and keep in there for as long as it’s in
the file serving cache instance.

Even with a thread performing ``readahead()``, it’s possible for the I/O
thread to block (or be stuck in an operation that takes more time than
absolutely necessary), increasing latency when handling other
connections assigned to them. This why I’ve been thinking for quite a
while now on how to introduce a work-stealing scheduler to Lwan, with a
watchdog thread to determine if worker threads are not making any kind
of progress; but this is something for the future, I guess.

(Recent advancements in things like ``io_uring`` and the AIO subsystem
may change how these things are used in Lwan.
`PSI <https://www.kernel.org/doc/html/latest/accounting/psi.html>`__ can
be used to avoid doing things if the system is under pressure. I have
not investigated those in depth so far.)

Coroutine changes
=================

There has been a few minor tweaks in the coroutine implementation.
Nothing groundbreaking, but worth mentioning anyway.

The ``data`` pointer has been removed from the coro structure, as it can
be simply passed as parameter to the function implementing the
coroutine. This required the trampoline function for x86-64 to be
written in assembly since one of the registers used for parameter
passing are not in the list of caller-saved registers (and thus not
saved/restored by the context swapping routine), but otherwise,
everything seems to be working as expected.

Deferred callbacks are now stored in an array rather than using a linked
list. This makes it cheaper to use defer (less calls to ``malloc()`` for
each ``coro_defer()`` call), which has become an important aspect in how
resources are cleaned up in Lwan. In order to reduce heap memory
allocations, the array is allocated initially inline with the coroutine
struct and moves to the heap if necessary; this cuts two round trips to
the memory allocator per connection in the usual case (this optimization
is available for all array structs if desired; more on this below).

The following table shows the number of ``malloc()`` calls for 100,000
requests to a “Hello, World” handler and the impact of inlining deferred
calls, for both keep-alive and close connections (with 1000 concurrent
connections):

========== =================== ==================
Connection Malloc Calls Before Malloc Calls After
========== =================== ==================
Keep-Alive 1,031               931
Close      300,731             200,728
========== =================== ==================

An embarassing fix in the coroutine implementation has been in how the
stack is aligned on x86-64. In some situations, Lwan was crashing (with
a SIGSEGV no less) on instructions that were not meant to cause this
kind of signal (e.g. it would crash when Lua was converting a number
into string). Tools such as Valgrind, sanitizers, and debuggers weren’t
that helpful to pinpoint the location. It turns out that how the stack
pointer for coroutines were aligned was incorrect: had ``sprintf()``
(what Lua uses to convert floating point numbers to strings) been
implemented using x87, this would work fine; however, SSE requires
aligned memory to work, so things were crashing on such a trivial
operation. It’s now aligned on a 16-byte boundary, adjusted to be
aligned on an 8-byte boundary right before the trampoline routine is
called. This one-line change took me a lot more hours than I care to
admit, but it’s now finally fixed. It was the first time I used
`rr <https://rr-project.org/>`__, and it’s now an integral part of my
toolbelt.

Sending responses
=================

For some responses, the ``writev()`` system call was used, so that the
response headers and body could be sent to the wire with a single
syscall. However, the kernel has to copy the I/O vector array, validate
it, and then perform the write operation; this has a relatively high
cost, and if one is trying to send a small response, this cost might not
pay off. I haven’t considered this and always wondered why that was the
case when ``writev()`` was used to build responses (e.g. using multiple
``struct iovec`` elements pointing to header names and values instead of
building the response header in memory and sending that). I was
surprised, then, to learn that by reusing the buffer designated for the
response headers and writing the body there (given there was enough
space), and using ``send()`` instead, the RPS rate increased by ~10%.

.. code:: c

   void lwan_response(struct lwan_request *request, enum lwan_http_status status)
   {
       /* ... */
       char headers[DEFAULT_HEADERS_SIZE];

       /* ... */

       char *resp_buf = lwan_strbuf_get_buffer(response->buffer);
       const size_t resp_len = lwan_strbuf_get_length(response->buffer);
       if (sizeof(headers) - header_len > resp_len) {
           /* writev() has to allocate, copy, and validate the response vector,
            * so use send() for responses small enough to fit the headers
            * buffer.  On Linux, this is ~10% faster.  */
           memcpy(headers + header_len, resp_buf, resp_len);
           lwan_send(request, headers, header_len + resp_len, 0);
       } else {
           struct iovec response_vec[] = {
               {.iov_base = headers, .iov_len = header_len},
               {.iov_base = resp_buf, .iov_len = resp_len},
           };

           lwan_writev(request, response_vec, N_ELEMENTS(response_vec));
       }
   }

In order to increase the performance of pipelined requests, Lwan will
also call ``send()`` with the ``MSG_MORE`` flag. This should cause in
less TCP segments being sent over the wire, significantly improving the
RPS rate (~20% higher if I’m not mistaken). This is akin to setting the
``TCP_CORK`` socket flag, but not only this is more portable, system
calls are saved; nonetheless, the flag that controls if the I/O wrappers
will set that flag still mentions the cork flag. (Linux has TCP
autocorking, which in theory should make this optimization useless, but
in my limited testing it didn’t help that much.) The ``writev()`` system
call, which is still used for those responses that are larger than it
would fit in the response headers buffer, doesn’t take a flags
parameter; however, it’s possible to use ``sendmsg()`` to the same
effect (it also takes the same I/O vector and has the same behavior as
``writev()`` when it comes to short writes due to non-blocking sockets.)

Adding to the “I’ve been adopting lookup tables whenever I can” comment
above: in order to determine if a response has a body, instead of a
table, the actual flags in the request struct that are used to determine
the HTTP verb encodes this information: if their least-significant-bit
is set, then the response should contain a body; otherwise, only headers
will be sent. Went from an array lookup to a mere mask. Still a table,
just encoded differently.

CPU topology aware thread pinning / scheduling
==============================================

One of the things that Lwan has been doing since the beginning was to
allocate a big chunk of memory to containing information about client
connections. Indexed by the file descriptor, looking up the element is
quick and efficient; however also makes it possible for false sharing to
happen (the struct is exactly 32 bytes on x86-64, so that two fit in a
cache line), so connections are scheduled to threads in such a way that
this is avoided.

Previously, however, this would only consider that the CPU topology for
my personal laptop was the gold standard. Anything different and it
would mean that it would probably make the problem even worse. (I’m not
kidding when I say that this project is but a toy.)

Now, Lwan, at least on x86_64 Linux (as it relies on information exposed
by sysfs rather than messing around with ``cpuid`` and the likes), reads
the CPU topology and uses that information to not only pre-schedule all
connections correctly (minimizing a little bit of the work necessary
whenever one is accepted), but to also pin the threads to the correct
logical CPU.

Continuous Fuzz-Testing
=======================

Writing your own parser, especially when it comes to something that’s
connected to a network socket, always should raise suspicions. Parsers
can be tricky to get right, and it’s very easy to accidentally trigger a
footgun when doing so in a language like C.

Nevertheless, I still do it; this project is but a hobby to me, and
running with scissors is part of why it’s enjoyable to me. As careful as
I am with it (or would like to think I am), it’s still developed while
I’m tired from work or when I had a few beers; in other words, I needed
to test the project methodically. I had used fuzz-testers before, but
never let them running overnight or over extended periods of time; my
main machine is a laptop, and overheating is an issue.

It was much to my surprise, then, when the folks at Google accepted my
weekend project on `OSS-Fuzz <https://github.com/google/oss-fuzz/>`__.
So far, it has `found a few issues, which were promptly
fixed <https://bugs.chromium.org/p/oss-fuzz/issues/list?can=1&q=lwan>`__;
however, although it’s still hard at work, generating some heat
somewhere, the parser proved to be pretty resilient. I’m pretty happy
with the results.

This of course is only testing the request parser, and there’s more to a
web server than that; some of which aren’t that easy to fuzz-test (at
least not in an automated way). Most of the code being fuzzed is the
more important (and network-facing) request parsing code; coverage for
this is around 15%, which is pretty decent all things considered. The
configuration file parser is also being fuzzed, although the work has
just recently started (I don’t have a lot of information on this yet).
Time permitting, I’ll add more fuzzers to the mix.

As I write this, over 56 trillion tests in the past 30 days (counting only
the tests with `libFuzzer <https://llvm.org/docs/LibFuzzer.html>`__,
although `AFL <http://lcamtuf.coredump.cx/afl/>`__ is also used), which is
nothing short of amazing.

Portability
===========

The astute reader, or at least one that has been following Lwan for a
while, might have noticed that portability has been mentioned a few
times in this article. This was not a concern a few years ago, but since
then, Lwan has been ported to work on BSD systems as well (mostly by
implementing epoll on top of kqueue, and providing a sendfile I/O
wrapper that works regardless of the underlying system), although it has
been only tested on FreeBSD, macOS, and OpenBSD. (Recent OpenBSDs might
require some tinkering, as they enforce the stack pointer to be within
pages mapped with a specific flag.)

You can read more about how portability has been achieved by reading my
`blog post on using the non-standard #include_next preprocessor
directive <https://tia.mat.br/posts/2018/06/28/include_next_and_portability.html>`__,
which saved me from writing abstraction layers.

Declaring new Lua metamethods
=============================

Another change that might improve the comfort of people using Lwan with
Lua scripts is that it’s easier to add new metamethods to the request
table.

One just declares a new C function with the ``LWAN_LUA_METHOD`` macro,
and, during startup, Lwan will attach that function to the request
metatable as a metamethod. (One can call
``lwan_lua_get_request_from_userdata()`` to obtain a
``struct lwan_request *`` from the first parameter in the C
implementation of one of these metamethods.)

.. code:: c

   LWAN_LUA_METHOD(say)
   {
       struct lwan_request *request = lwan_lua_get_request_from_userdata(L);
       size_t response_str_len;
       const char *response_str = lua_tolstring(L, -1, &response_str_len);

       lwan_strbuf_set_static(request->response.buffer, response_str,
                              response_str_len);
       lwan_response_send_chunk(request);

       return 0;
   }

This macro works by adding a struct to a certain section in the
executable, so new application-specific metamethods can be linked
together with Lwan without having to modify Lwan itself.

.. code:: c

   #define LWAN_LUA_METHOD(name_)                                                 \
       static int lwan_lua_method_##name_(lua_State *L);                          \
       static const struct lwan_lua_method_info                                   \
           __attribute__((used, section(LWAN_SECTION_NAME(lwan_lua_method))))     \
               lwan_lua_method_info_##name_ = {.name = #name_,                    \
                                               .func = lwan_lua_method_##name_};  \
       static int lwan_lua_method_##name_(lua_State *L)

All functions in ``lwan-lua.c`` are now implemented this way to serve as
an example on how to use this feature.

Declaring Handlers and Modules
==============================

In order to make it more portable, safer, and easier to declare a
handler function in Lwan, a macro similar to ``LWAN_LUA_METHOD()`` has
been provided: ``LWAN_HANDLER()``. It will declare a handler function
and a ``struct lwan_handler_info`` in a specific section in the
executable, making it easier for the configuration file reader to find
it every time, regardless of how that platform exports symbols, make it
impossible to refer to any exported symbol as a handler from the
configuration file, and slightly simplifies declaring a handler function
(without requiring, for instance, changing tables to make the
configuration file reader happy).

Defining a handler with this macro is trivial:

.. code:: c

   LWAN_HANDLER(brew_coffee)
   {
       /* Placeholder handler to force the linker to define __start_lwan_handler and
        * __stop_lwan_handler.  */
       return HTTP_I_AM_A_TEAPOT;
   }

As is looking it up (the linker does the job of registering each
handler):

.. code:: c

   __attribute__((no_sanitize_address))
   static void *find_handler(const char *name)
   {
       extern const struct lwan_handler_info SECTION_START(lwan_handler);
       extern const struct lwan_handler_info SECTION_END(lwan_handler);
       const struct lwan_handler_info *handler;

       for (handler = __start_lwan_handler; handler < __stop_lwan_handler;
            handler++) {
           if (streq(handler->name, name))
               return handler->handler;
       }

       return NULL;
   }

A similar feature has been provided for modules, making it even possible
to list them from the Lwan command-line (``lwan -m`` and ``lwan -H`` to
list modules and handlers, respectively). However, instead of specifying
a function as with ``LWAN_HANDLER()``, one specifies a
``struct lwan_module`` with ``LWAN_REGISTER_MODULE()``.

.. code:: c

   static const struct lwan_module module = {
       .create = serve_files_create,
       .create_from_hash = serve_files_create_from_hash,
       .destroy = serve_files_destroy,
       .handle_request = serve_files_handle_request,
       .flags = HANDLER_PARSE_ACCEPT_ENCODING,
   };

   LWAN_REGISTER_MODULE(serve_files, &module);

In all cases, the only symbol that ends up being visible is the
associated ``_info`` struct; the handler function and module struct are
not exported.

Changes to the String Buffer
============================

A HTTP/1.x server is essentially a program that transforms strings into
strings over a network connection, so some sort of facility to create
them efficiently is often desired. In Lwan, this is ``struct strbuf``,
which has seen some trivial changes over the years, mainly to reduce the
amount of memory they need to work with (as every request struct has to
carry one of them).

It initially had two fields, ``used`` and ``capacity``, where
``capacity`` would be always the next power of two after ``used`` (and
the buffer would be reallocated accordingly). The ``capacity`` field has
now been removed; it’s now derived from ``used``, as it’s cheap to align
to the next power of two to calculate it whenever needed.

Each connection triggered the allocation of a buffer for its associated
request ``struct strbuf``, even if it might not be used (e.g. for
streaming requests, such as file serving). A ``strbuf`` is now
initialized pointing to an empty static string (with the ``STATIC`` flag
set); that’ll delay the allocation for when it’s truly needed. The
following table builds on the results from the coroutine optimizations,
optimizing the base case even further:

========== =================== ==================
Connection Malloc Calls Before Malloc Calls After
========== =================== ==================
Keep-Alive 931                 831
Close      200,731             100,728
========== =================== ==================

Hash Table Changes
==================

The hash table has also seen some changes, most notably the ability to
rehash (although the heuristic to determine if rehashing is required
might need some work). The hash value is kept alongside each bucket
element, slightlyy alleviating the cost.

Another simple change that has been implemented is that, when an entry
is removed from a bucket, instead of defragmenting that bucket, the last
element is copied on top of the element being removed. Since order in a
bucket isn’t important, this made removing elements quite a bit more
efficient (and given that the hash table is an integral part of the
cache subsystem, this is important to keep the write lock locked for the
minimum amount of time.)

I’ve experimented with other techniques to implement a hash table,
including using robin-hood hashing, but I’m keeping it this way for the
moment. It’s something I want to revisit someday. (Also played with
hashing functions, including using AES-NI instructions instead of the
CRC32C from SSE4.2, but never got as far as integrating the experiments
in Lwan.)

Gracefully Closing Sockets
==========================

The other day I received a bug report where pages served by Lwan and
loaded by W3M would take a long time to load. Not only this is unusual
because someone is actually using Lwan, but also because someone is
actually using W3M in 2019. Nevertheless, this was an interesting bug
with a simple fix: W3M implements only HTTP/1.0, and until the server
closes the connection, it won’t start parsing and displaying the results
(the connection would be closed after the keep-alive timeout was
reached, which is roughly 15s); now Lwan closes the connection as soon
as it’s done processing it, if it’s not marked as keep-alive. Easy to
spot using something like ``strace``.

Closing a TCP socket, however, isn’t as simple as just calling
``close()``: there might be some enqueued packets not yet acknowledged
by the peer, so the usual solution to this is to call
``shutdown(fd, SHUT_WR)`` to stop any kind of transmission and wait on a
loop calling ``read()`` until it returns ``0`` (signaling that the peer
has closed the connection), at which point it’s safe to just call
``close()`` and consider that the connection has been closed.

However, from my testing, the scenario where one actually needs to wait
on a ``read()`` loop isn’t that common, especially with the big fat
pipes that are common these days; so, in order to minimize the number of
system calls made in the happy path, Lwan now checks if there are any
pending bytes to be sent/acknowledged by the peer before proceeding with
the usual method. This should equate to 2 system calls to close a
connection (the ``ioctl()`` and ``close()``), rather than at least 3
(``shutdown()`` + ``read()`` + ``close()``) in the happy path.

.. code:: c

   static void graceful_close(struct lwan *l,
                              struct lwan_connection *conn,
                              char buffer[static DEFAULT_BUFFER_SIZE])
   {
       int fd = lwan_connection_get_fd(l, conn);

       while (TIOCOUTQ) {
           /* This ioctl isn't probably doing what it says on the tin; the details
            * are subtle, but it seems to do the trick to allow gracefully closing
            * the connection in some cases with minimal system calls. */
           int bytes_waiting;
           int r = ioctl(fd, TIOCOUTQ, &bytes_waiting);

           if (!r && !bytes_waiting) /* See note about close(2) below. */
               return;
           if (r < 0 && errno == EINTR)
               continue;

           break;
       }

       if (UNLIKELY(shutdown(fd, SHUT_WR) < 0)) {
           if (UNLIKELY(errno == ENOTCONN))
               return;
       }

       for (int tries = 0; tries < 20; tries++) {
           ssize_t r = read(fd, buffer, DEFAULT_BUFFER_SIZE);

           if (!r)
               break;

           if (r < 0) {
               switch (errno) {
               case EINTR:
                   continue;
               case EAGAIN:
                   coro_yield(conn->coro, CONN_CORO_WANT_READ);
                   continue;
               default:
                   return;
               }
           }

           coro_yield(conn->coro, CONN_CORO_YIELD);
       }

       /* close(2) will be called when the coroutine yields with CONN_CORO_ABORT */
   }

(On platforms where that ``ioctl()`` isn’t available, the usual method
is used instead. ``TIOCOUTQ`` is Linux-specific, but it’s defined to
``0`` or the equivalent value in other OSes with some ``#include_next``
magic, so that the ``while()`` loop there works as a loop to both handle
the ``ioctl()`` call being interrupted and check if that ``ioctl`` is
available on that platform.)

MIME Type table improvements
============================

Lwan contains an internal MIME Type table based on the public domain
table made for the Apache httpd project. The same file is used by
``mimegen``, a program built and used only during build time, that
generates a header file containing data suitable to be searched with
``bsearch()``. (The data in the header file is also compressed, saving a
few dozen kilobytes in the final executable.)

The table was initially laid out as an array of
``struct { const char *extension; const char *mime_type; }``, all
pointing to different positions within a character array. In other
words, not only only 4 entries could fit in a cache line (assuming
x86-64 here, with 8-byte pointers and 64-byte cache lines), each access
would mean that other cache lines had to be used to proxy the character
array.

With some trivial changes, this has been significantly improved: instead
of having a single table with extension+type, two (in-sync) tables are
provided. Search happens only in the first table; once an item is found
there, its position within the first table is used as an index in the
second table. This greatly reduces the cache pressure (each item in the
first table is fixed at 8 characters, so double the cache density for
``bsearch()`` to breeze through quickly).

The change in the function to look up a MIME type given a file name
didn’t change much from 2014:

.. code:: c

   const char *
   lwan_determine_mime_type_for_file_name(const char *file_name)
   {
       char *last_dot = strrchr(file_name, '.');
       if (UNLIKELY(!last_dot))
           goto fallback;

       STRING_SWITCH_L(last_dot) {
       case STR4_INT_L('.','j','p','g'):  return "image/jpeg";
       case STR4_INT_L('.','p','n','g'):  return "image/png";
       case STR4_INT_L('.','h','t','m'):  return "text/html";
       case STR4_INT_L('.','c','s','s'):  return "text/css";
       case STR4_INT_L('.','t','x','t'):  return "text/plain";
       case STR4_INT_L('.','j','s',0x20): return "application/javascript";
       }

       if (LIKELY(*last_dot)) {
           char *extension, *key = last_dot + 1;

           extension = bsearch(key, uncompressed_mime_entries, MIME_ENTRIES, 8,
                               compare_mime_entry);
           if (LIKELY(extension))
               return mime_types[(extension - (char*)uncompressed_mime_entries) / 8];
       }

   fallback:
       return "application/octet-stream";
   }

This idea is far from novel; in fact, it’s common in video-game
development and is known as `data-oriented
design <https://en.wikipedia.org/wiki/Data-oriented_design>`__.

(I investigated the possibility of using
`gperf <https://www.gnu.org/software/gperf/>`__ here instead, but
decided against it as this would require two build-time programs instead
of one for this feature.)

Accepting Clients
=================

While it’s possible to wake a worker thread blocked on ``epoll_wait()``
by adding a file descriptor to its watched set (by watching ``EPOLLOUT``
instead of ``EPOLLIN``, even though you want to read from the socket
before sending a response, as counter-intuitive as this might sound), I
found that this isn’t the best approach. (Don’t know why yet, though.)

Until recently, Lwan was using a pipe to send the file descriptor number
from the main thread (which accepts the connection) to the worker thread
that would forever own it. This worked well, but meant that every new
connection would require at least two system calls that were unrelated
to actually handling the connections: ``accept4()`` and ``write()``.
While pipes aren’t exactly slow (they’re just buffers in the kernel
anyway), it’s still a lot of overhead to write 4 bytes to another thread
in the same process.

Recent versions of Lwan uses a different approach: a lock-free
single-producer-single-consumer queue and an ``eventfd``, are used to
queue file descriptors until the “horde” has passed (or the queue got
full). (While the main thread is accepting connections, it’s handling a
“horde”; once ``accept4()`` returns a ``EAGAIN`` error, the horde is
gone and the main thread can proceed.) The eventfd is then used to wake
up the worker thread (“nudging” in Lwan jargon), at which point it
proceeds to add the file descriptors to the sets, creates the associated
coroutines, and stuff like this.

In ``lwan-thread.c``, we define a function that tries adding a new
client to a worker thread a few times, dropping the connection if that
worker thread is somehow hosed even after repeated attempts at nudging
it:

.. code:: c

   void lwan_thread_add_client(struct lwan_thread *t, int fd)
   {
       for (int i = 0; i < 10; i++) {
           bool pushed = spsc_queue_push(&t->pending_fds, fd);

           if (LIKELY(pushed))
               return;

           /* Queue is full; nudge the thread to consume it. */
           lwan_thread_nudge(t);
       }

       lwan_status_error("Dropping connection %d", fd);
       /* FIXME: send "busy" response now, even without receiving request? */
       close(fd);
   }

And in ``lwan.c``, you can see how the coroutine that handles incoming
connections batches each incoming herd and minimizes the amount of
nudges to wake up the worker threads:

.. code:: c

   static ALWAYS_INLINE int schedule_client(struct lwan *l, int fd)
   {
       struct lwan_thread *thread = l->conns[fd].thread;

       lwan_thread_add_client(thread, fd);

       /* Connections are pre-scheduled, but we need a thread index, not a
        * pointer to a struct lwan_thread. */
       return (int)(thread - l->thread.threads);
   }

   /* Using -1, 0, and 1 for enumeration values allows you to test them
    * using only comparisons with 0.  */
   enum herd_accept { HERD_MORE = 0, HERD_GONE = -1, HERD_SHUTDOWN = 1 };

   struct core_bitmap {
       uint64_t bitmap[4]; /* 256 processors should be enough for everybody */
   };

   static ALWAYS_INLINE enum herd_accept
   accept_one(struct lwan *l, struct core_bitmap *cores)
   {
       int fd = accept4((int)main_socket, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);

       if (LIKELY(fd >= 0)) {
           int core = schedule_client(l, fd);

           cores->bitmap[core / 64] |= UINT64_C(1)<<(core % 64);

           return HERD_MORE;
       }

       switch (errno) {
       case EAGAIN:
           return HERD_GONE;

       case EBADF:
       case ECONNABORTED:
       case EINVAL:
           if (main_socket < 0) {
               lwan_status_info("Signal 2 (Interrupt) received");
           } else {
               lwan_status_info("Main socket closed for unknown reasons");
           }
           return HERD_SHUTDOWN;

       default:
           lwan_status_perror("accept");
           return HERD_MORE;
       }
   }

   static int accept_connection_coro(struct coro *coro, void *data)
   {
       struct lwan *l = data;
       struct core_bitmap cores = {};

       while (coro_yield(coro, 1) & ~(EPOLLHUP | EPOLLRDHUP | EPOLLERR)) {
           enum herd_accept ha;

           do {
               ha = accept_one(l, &cores);
           } while (ha == HERD_MORE);

           if (UNLIKELY(ha > HERD_MORE))
               break;

       /* A thread bitmap is maintained: accept_one() will set the nth bit
        * to signify that the nth thread needs to be nudged.  This loop
        * will then quickly go through every set bit in that bitmap and
        * nudge the appropriate thread. */
           for (size_t i = 0; i < N_ELEMENTS(cores.bitmap); i++) {
               for (uint64_t c = cores.bitmap[i]; c; c ^= c & -c) {
                   size_t core = (size_t)__builtin_ctzl(c);
                   lwan_thread_nudge(&l->thread.threads[i * 64 + core]);
               }
           }
           memset(&cores, 0, sizeof(cores));
       }

       return 0;
   }

On any other platform other than Linux, a pipe is used for the same
effect; it just doesn’t scale as well (requires two file descriptors per
worker thread instead of just one, allocates a larger kernel buffer for
no purpose whatsoever, etc.).

Weirdly enough, as much as the approach of adding the client sockets
directly to the worker thread’s epoll set with an ``EPOLLOUT`` event
rather than using this queue+eventfd mechanism reduced the amount of
system calls, the throughput when using non-keeepalive connections has
been measurably reduced (and not just in the noise). I don’t know why,
and haven’t investigated this yet.

(The current approach limits the number of worker threads that Lwan can
spawn, as threads are only nudged when connections have been assigned to
them. Currently it’s at 256 threads, which is fine for many systems
today – and certainly way better than any machine I have access to.)

Sample programs
===============

FreeGeoIP
---------

One of the first sample applications that I’ve written for Lwan was an
implementation of the ``freegeoip.net`` service. It’s been working fine
so far, serving a few hundred thousands requests per day (down from a
few million per day), using around 3MB of memory. It’s also pretty
stable: the server has been recently rebooted to update the kernel, and
before this happened, I observed that the service was chugging along for
over a year.

I’m pretty pleased with this, especially if one considers that the
original service that this has been cloned from caused a lot of
maintenance headache and was eventually abandoned.

There’s a `live version of this application running
here <https://freegeoip.lwan.ws>`__.

Clock
-----

A newer sample is the clock application. This generates a never-ending
GIF file, served with chunked encoding, that draws the current time in a
variety of styles: something that resembles a 7-segment display;
`xdaliclock <https://www.jwz.org/xdaliclock/>`__; and a Tetris-like
animation (where falling blocks are rotated until they fit and form
digits).

This is but a hack, so it doesn’t work in all browsers (it’s known to be
broken on Safari for instance), but in supported ones, it’s a cheap way
to make animations without JavaScript, or to stream content from a
server.

.. figure:: https://time.lwan.ws/dali.gif
   :alt: xdaliclock rendered on-the-fly
   :align: center

   Look at those melting digits! No JavaScript or CSS required.

(And, of course, the “never-ending” aspect isn’t actually correct. Bots
would try to download the GIFs, without any kind of timeout. I’ve seen
bots trying to download those for days. It now forces the page to be
reloaded every hour and limits each GIF to a little bit more than that.
Implement timeouts when writing crawlers, people.)

There’s a `live version of this application running
here <https://time.lwan.ws>`__.

Proxy Protocol
==============

Putting Lwan behind a proxy is a common scenario to workaround the lack
of two features: virtual hosts and TLS. Both are somewhat trivial to
implement, but I haven’t gotten around supporting any of them because,
in my use case, I’m perfectly happy to stick a
`Varnish <https://www.varnish-cache.org>`__ cache and a `TLS
terminator <https://hitch-tls.org/>`__ in front of it. In order to allow
functions such as ``lwan_request_get_remote_address()`` to return the
correct client address (instead of, say, ``::1``), Lwan has to be aware
that it’s being proxied.

A popular protocol for this, pioneered by
`HAProxy <http://www.haproxy.org/>`__, is aptly named `PROXY
protocol <https://www.haproxy.org/download/1.8/doc/proxy-protocol.txt>`__.
An implementation for both versions 1 and 2 has been contributed to Lwan
by Malthe Borch as one of the first open source contributions to Lwan;
thank you very much! (This is disabled by default because it should only
be used if Lwan is known to be behind a reverse proxy. Inadvertently
enabling it would allow anyone to easily spoof the client IP address to
request handlers.)

(I did investigate using
`kTLS <https://netdevconf.info/1.2/papers/ktls.pdf>`__, but didn’t go
that far at the time as it wasn’t part of mainline Linux kernel. I might
give it a try someday now that it is, though.)

WebSockets
==========

Lwan has also gained the ability to function as a WebSockets server. The
protocol is trivial to implement (wonky handshaking and unoptimal
framing notwithstanding), but defining an API that’s usable from C is
quite challenging. I’ve tried a few combinations but never got to the
point where I could find something I liked; I have some ideas to try but
they’re still pretty fuzzy in my head.

The program below illustrates the current state of the API: while it
seems straightforward enough for an endpoint to check if a WebSocket
connection upgrade was requested by the client, and trivial to send
stuff over the wire, there are a few drawbacks with the current
situation:

-  PING requests will only be processed by
   ``lwan_response_websocket_read()``; this example will never respond
   to a PING packet and might be disconnected by a client.
-  Both the read and the write primitives are blocking; it’s not
   possible to write something that can both wait for commands and
   occasionally send data over the wire. It should be possible to, for
   instance, write an echo server, but it’s not possible to implement
   `socket.io <https://socket.io>`__ for instance.
-  There are currently no tests for WebSockets as well; testing is
   performed manually by using the WebSockets inspection tool in web
   browsers, but automated tests would be preferred. I suspect that
   reading from a WebSocket is broken after a lot of unrelated changes
   in the main loop.

.. code:: c

   LWAN_HANDLER(ws)
   {
       /* Requesting an upgrade will send an appropriate response if the
        * request contained a valid handshake, returning HTTP code 101 in that
        * case. Any other error code won't generate a default response,
        * so the handler can return at this point.
        *
        * Having a separate function to upgrade a WebSocket connection
        * (as opposed to having a flag in a handler that would try to do
        * this automatically) is useful to allow people to write, for instance,
        * authorization code to explicitly upgrade a connection only if
        * certain checks passes. */
       enum lwan_http_status status = lwan_request_websocket_upgrade(request);

       if (status != HTTP_SWITCHING_PROTOCOLS)
           return status;

       while (true) {
           /* Similar to chunked encoding and server-sent events, the response
            * string buffer contains the data that is going to the wire, or
            * data that was received from the wire.  The strbuf is reset every
            * time a response is sent or received. */
           lwan_strbuf_printf(response->buffer, "Some random integer: %d", rand());
           lwan_response_websocket_write(request);
           lwan_request_sleep(request, 1000);
       }

       return HTTP_OK;
   }

Rewrite Module
==============

Inspired by Apache httpd’s ``mod_rewrite``, a module with similar
functionality has been implemented in Lwan. Instead of a bespoke syntax,
though, it can be set up using the same configuration file syntax;
albeit more verbose, it’s significantly easier to understand.

Based on `Lua’s pattern matching
engine <https://www.lua.org/manual/5.3/manual.html#6.4.1>`__, which were
chosen because they’re not only powerful enough, but it’s also a
`DFA <https://en.wikipedia.org/wiki/Deterministic_finite_automaton>`__,
which makes it a lot harder for an unbounded backreference to DoS the
server (as it doesn’t support any).

This is how it looks in the configuration file:

::

   # Instantiate the "rewrite" module to respond in "/pattern".
   rewrite /pattern {
       # Match /patternfoo..., and redirect to a new URL.
           pattern foo/(%d+)(%a)(%d+) {
                   redirect to = /hello?name=pre%2middle%3othermiddle%1post
           }
       # Match /patternbar/... and rewrite as /hello...
           pattern bar/(%d+)/test {
                   rewrite as = /hello?name=rewritten%1
           }
       # Use Lua to determine where the client should redirect to
           pattern lua/redir/(%d+)x(%d+) {
                   expand_with_lua = true
                   redirect to = '''
                       function handle_rewrite(req, captures)
                           local r = captures[1] * captures[2]
                           return '/hello?name=redirected' .. r
                       end
                   '''
           }
       # Use Lua to determine how to rewrite the request
           pattern lua/rewrite/(%d+)x(%d+) {
                   expand_with_lua = true
                   rewrite as = """function handle_rewrite(req, captures)
                           local r = captures[1] * captures[2]
                           return '/hello?name=rewritten' .. r
                       end"""
           }
   }

Without ``expand_with_lua`` set (or set to ``false``), the expansion
rule is trivial: ``%n`` will expand to the n-th capture; everything else
will be copied verbatim. When set, a ``handle_rewrite()`` function has
to be defined; the ``req`` parameter contains the same metamethods
available for handlers in the ``lua`` module, and ``captures`` is a
table containing the pattern matches.

As a measure against bad configuration, URLs can’t be rewritten over 4
times (otherwise, a 500 Internal Error response is generated instead).

(This module prompted a change in the configuration file parser that
allows a section to be “isolated”: while the file is being read, if it’s
in a start section line, one can ask the configuration reader to isolate
the section. What this does is that it creates a proxy configuration
struct that has a view of only that particular section. This isolated
configuration object is passed to a module, that can read as usual
without having to worry about overreading the main configuration.)

Snippets
========

Non-boolean predicates
----------------------

C lacks option types, but sometimes you can get creative with what you have. 
For instance, I like how elegant this small piece of code that determines
the temporary directory turned out:

.. code:: c

   static const char *is_dir(const char *v)
   {
       struct stat st;

       if (!v)
           return NULL;

       if (*v != '/')
           return NULL;

       if (stat(v, &st) < 0)
           return NULL;

       if (!S_ISDIR(st.st_mode))
           return NULL;

       if (!(st.st_mode & S_ISVTX)) {
           lwan_status_warning(
               "Using %s as temporary directory, but it doesn't have "
               "the sticky bit set.",
               v);
       }

       return v;
   }

   static const char *
   get_temp_dir(void)
   {
       const char *tmpdir;

       tmpdir = is_dir(secure_getenv("TMPDIR"));
       if (tmpdir)
           return tmpdir;

       tmpdir = is_dir(secure_getenv("TMP"));
       if (tmpdir)
           return tmpdir;

       tmpdir = is_dir(secure_getenv("TEMP"));
       if (tmpdir)
           return tmpdir;

       tmpdir = is_dir("/var/tmp");
       if (tmpdir)
           return tmpdir;

       tmpdir = is_dir(P_tmpdir);
       if (tmpdir)
           return tmpdir;

       return NULL;
   }

The ``is_dir()`` predicate returns the same input parameter if it turns
that its condition holds (or ``NULL`` if it doesn’t), and it is used to
drive the conditions in ``get_temp_dir()`` as well as the return value
for that function. I don’t think that this could get any cleaner.

(I was actually going to write a blog post on how to create temporary
files safely – which these funcions are part of – but `Lennart
Poettering <https://systemd.io/TEMPORARY_DIRECTORIES>`__ beat me to it.)

Boolean flags to bitmask without branching
------------------------------------------

Sometimes, it’s necessary to convert one set of bitwise mask into
another set of bitwise mask. Something like this:

.. code:: c

   if (flag1) flags |= SOME_BIT_MASK1;
   if (flag2) flags |= SOME_BIT_MASK2;

In order to get rid of those branches, one can extend the ``bool`` type
into ``typeof(flags)``, and shift it by ``log2(mask)``. Lwan does this
with some flags:

.. code:: c

   #define REQUEST_FLAG(bool_, name_)                                             \
       ((enum lwan_request_flags)(((uint32_t)lwan->config.bool_)                  \
                                  << REQUEST_##name_##_SHIFT))
   static_assert(sizeof(enum lwan_request_flags) == sizeof(uint32_t),
                 "lwan_request_flags has the same size as uint32_t");

Which is then used like so:

.. code:: c

   enum lwan_request_flags flags =
           REQUEST_FLAG(proxy_protocol, ALLOW_PROXY_REQS) |
           REQUEST_FLAG(allow_cors, ALLOW_CORS);
