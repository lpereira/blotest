include_next and portability
============================

One of the decisions I took early on while writing Lwan was to only support
Linux, and think about portability later; this decision was influenced by the
way the `OpenBSD project approaches portability <https://www.openbsd.org/papers/portability.pdf>`_.

In retrospect, this was a good decision: this avoided many of the pitfalls
associated in `writing abstractions too early in the game
<http://wiki.c2.com/?PrematureAbstraction>`_.  It also made the code cleaner:
the abundance of C preprocessor usage, common in some portable code, hinders
legibility and maintainability.  Of course, this decision made it
challenging to port it to other operating systems.

I was content with this decision -- until people began asking for BSD and Mac
ports.  With the exception of some system calls (e.g.  epoll, or the Linux
`sendfile <http://man7.org/linux/man-pages/man2/sendfile.2.html>`_ variant), porting shouldn't be surprising.  Ideally, having the code
largely ``#ifdef`` free would be ideal, so I had to find a way to make this happen.

While reading the GCC manual, I found out about an extension -- that also
happens to be `implemented by Clang
<https://clang.llvm.org/docs/LanguageExtensions.html>`_ -- that fit perfectly
this scenario: `wrapper headers
<https://gcc.gnu.org/onlinedocs/cpp/Wrapper-Headers.html>`_.  It's a C
preprocessor extension that includes the next file in the include lookup
path.  With this extension, it's possible to write our own substitute header
files, named after standard header files:

.. code-block:: c

    #include_next <stdlib.h> /* Include stdlib.h from system includes */

    #ifndef MISSING_STDLIB_H_
    #define MISSING_STDLIB_H_

    #if !defined(HAVE_MKOSTEMP)
    int mkostemp(char *tmpl, int flags);
    #endif

    #if !defined(HAVE_REALLOCARRAY)
    void *reallocarray(void *optr, size_t nmemb, size_t size);
    #endif

    #endif /* MISSING_STDLIB_H_ */

Have it in a directory named, say, "missing", and modify the header lookup path
so it is looked up first by the compiler.  This is easily accomplished in CMake
by specifying an include directory with the ``BEFORE`` option:

.. code-block:: c

    include_directories(BEFORE src/lib/missing)

(This just ensures that ``src/lib/missing`` will be passed before any other ``-I``
argument to the compiler, regardless of the order any other
``include_directories()`` macro is invoked.  Your build system might differ, this
is copied straight from Lwan's.)

Then it's just the matter of implementing these functions in terms of other
functions available in the system, and code using it will be none the wise: a
``#include <stdlib.h>`` line will include our wrapper header, which in turn will
include the system's ``stdlib.h`` header; it then might define, in this example,
additional prototypes, based on what the build system could determine during the
configuration phase.

This way, most ``#ifdefs`` are hidden away in a single file, making it a lot easier
to maintain and read the code.  No application-specific abstraction layer with
quirky semantics; just the familiar quirkiness from POSIX.

One of the things I'm particular proud of is the miniature `epoll(7)
<http://man7.org/linux/man-pages/man7/epoll.7.html>`_ implementation on top
of `kqueue <https://www.freebsd.org/cgi/man.cgi?query=kqueue&sektion=2>`_
(available in BSD systems).  I considered moving Lwan to use an abstraction
library (such as `libevent <http://libevent.org/>`_ or `libuv
<https://libuv.org/>`_) just for this, but was able to keep using its
event-handling loop as is.  Not only I understand 100% of it, it was a
worthwhile learning experience.  With ~120 lines of C code, this epoll
implementation is easier to wrap my head around than the thousands of lines
of code from those libraries.
