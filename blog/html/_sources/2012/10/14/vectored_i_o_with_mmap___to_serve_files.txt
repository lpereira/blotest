Vectored I/O with mmap() to serve files
=======================================

Previously, I’ve `improved file serving performance`_ in `lwan`_ by
dramatially cutting down on the number of system calls performed to serve a
file. However, for small files (< 16KiB), the throughput drop from the
``hello`` handler (which merely responds “Hello, World!”) was significant,
since lwan was still performing system calls to open, obtain the size, and
close the file.

I’ve experimented with userland caching before, but it never occurred to me
to use ``mmap()``. For the unitiated, this system call offers a way to map a
file into memory, by giving a pointer to the process virtual memory space,
that, when dereferenced, will perform the necessary disk I/O if the pages
were not already present in the kernel buffers. `Wikipedia`_ has more details
about it. Using ``mmap()`` greatly simplifies caching code by relaying it to
the kernel, closer to where the low level buffers are.

By using a memory-mapped buffer and `writev()`_ (which the ``hello`` handler
uses through lwan’s abstractions), the file serving performance improved
about 60%! Before the optimization, `weighttp`_ would be able to make ~170000
requests/s. Now, ~286000 requests/s can be made. (That’s on my laptop, a Core
i7 2640m, with 8GiB of RAM and without spinning platters.)

Of course, introducing caching also introduces a lot of complexity. Not only
the file serving handler almost doubled its size (from 350 lines to 610
lines), but I’ve had to add a hash table implementation (with around 430
lines) and a directory watcher that uses `inotify`_ at around 150 lines of C
code. In the order of 840 lines of code to improve performance by about 60%.
About 30% more lines of code to improve performance in 60% – not bad,
methinks.

On the other hand, the cache mechanism brings shared mutable state. This is
protected by mutexes, of course, but I’m not sure if I got it right. One more
reason to **not** use lwan in production.

As a bonus to these things, lwan now offers `deflated`_ content for the files
in the cache when asked.

.. _improved file serving performance:
    /posts/file_serving_with_few_syscalls/
.. _lwan: http://github.com/lpereira/lwan
.. _Wikipedia: https://en.wikipedia.org/wiki/Mmap
.. _writev(): https://en.wikipedia.org/wiki/Vectored_I/O
.. _weighttp: https://github.com/lighttpd/weighttp
.. _inotify: https://en.wikipedia.org/wiki/Inotify
.. _deflated: https://en.wikipedia.org/wiki/Deflate



.. author:: default
.. categories:: none
.. tags:: lwan,programming,C,linux
.. comments::