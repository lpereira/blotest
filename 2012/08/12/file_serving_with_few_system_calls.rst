File serving with few system calls
==================================

When I first wrote `lwan`_, file serving was not a primary goal. I’ve added
this capability later, never giving much thought to the number of system
calls required to serve one file. As a result, static file serving was quite
slow compared to “hello world” requests. Bored one day, I’ve decided to speed
this as much as I could.

Before optimizing, serving a file would look like this:

.. code-block:: c

    <... epoll_wait resumed> {{EPOLLIN, {u32=8, u64=8}}}, 16383,
    4294967295) = 1
    rt_sigprocmask(SIG_BLOCK, NULL, [], 8) = 0
    read(8, "GET / HTTP/1.0\r\n", 4096) = 16
    getcwd("/home/leandro/git/lwan/build", 4096) = 29
    lstat("/home/leandro/git/lwan/build/files_root",
    {st_mode=S_IFLNK|0777, st_size=33, ...}) = 0
    readlink("/home/leandro/git/lwan/build/files_root",
    "/home/leandro/git/blotest/output/", 4095) = 33
    lstat("/home", {st_mode=S_IFDIR|0755, st_size=4096, ...}) = 0
    lstat("/home/leandro", {st_mode=S_IFDIR|0755, st_size=4096, ...}) = 0
    lstat("/home/leandro/git", {st_mode=S_IFDIR|0775, st_size=4096, ...})
    = 0
    lstat("/home/leandro/git/blotest", {st_mode=S_IFDIR|0755,
    st_size=4096, ...}) = 0
    lstat("/home/leandro/git/blotest/output", {st_mode=S_IFDIR|0775,
    st_size=4096, ...}) = 0
    getcwd("/home/leandro/git/lwan/build", 4096) = 29
    lstat("/home/leandro/git/lwan/build/files_root",
    {st_mode=S_IFLNK|0777, st_size=33, ...}) = 0
    readlink("/home/leandro/git/lwan/build/files_root",
    "/home/leandro/git/blotest/output/", 4095) = 33
    lstat("/home", {st_mode=S_IFDIR|0755, st_size=4096, ...}) = 0
    lstat("/home/leandro", {st_mode=S_IFDIR|0755, st_size=4096, ...}) = 0
    lstat("/home/leandro/git", {st_mode=S_IFDIR|0775, st_size=4096, ...})
    = 0
    lstat("/home/leandro/git/blotest", {st_mode=S_IFDIR|0755,
    st_size=4096, ...}) = 0
    lstat("/home/leandro/git/blotest/output", {st_mode=S_IFDIR|0775,
    st_size=4096, ...}) = 0
    open("/home/leandro/git/blotest/output", O_RDONLY|O_NOATIME) = 9
    fstat(9, {st_mode=S_IFDIR|0775, st_size=4096, ...}) = 0
    close(9)                    = 0
    open("/home/leandro/git/blotest/output/index.html",
    O_RDONLY|O_NOATIME) = 9
    fstat(9, {st_mode=S_IFREG|0664, st_size=13200, ...}) = 0
    setsockopt(8, SOL_TCP, TCP_CORK, [1], 4) = 0
    write(8, "HTTP/1.0 200 OK\r\nContent-Length:"..., 100) = 100
    fadvise64(9, 0, 13200, POSIX_FADV_SEQUENTIAL) = 0
    sendfile(8, 9, NULL, 1400)  = 1400
    epoll_ctl(6, EPOLL_CTL_MOD, 8, {EPOLLOUT|EPOLLERR|0x2000, {u32=8,
    u64=8}}) = 0
    epoll_wait(6, {{EPOLLOUT, {u32=8, u64=8}}}, 16383, 1000) = 1
    sendfile(8, 9, NULL, 1400)  = 1400
    epoll_wait(6, {{EPOLLOUT, {u32=8, u64=8}}}, 16383, 1000) = 1
    sendfile(8, 9, NULL, 1400)  = 1400
    epoll_wait(6, {{EPOLLOUT, {u32=8, u64=8}}}, 16383, 1000) = 1
    sendfile(8, 9, NULL, 1400)  = 1400
    epoll_wait(6, {{EPOLLOUT, {u32=8, u64=8}}}, 16383, 1000) = 1
    sendfile(8, 9, NULL, 1400)  = 1400
    epoll_wait(6, {{EPOLLOUT, {u32=8, u64=8}}}, 16383, 1000) = 1
    sendfile(8, 9, NULL, 1400)  = 1400
    epoll_wait(6, {{EPOLLOUT, {u32=8, u64=8}}}, 16383, 1000) = 1
    sendfile(8, 9, NULL, 1400)  = 1400
    epoll_wait(6, {{EPOLLOUT, {u32=8, u64=8}}}, 16383, 1000) = 1
    sendfile(8, 9, NULL, 1400)  = 1400
    epoll_wait(6, {{EPOLLOUT, {u32=8, u64=8}}}, 16383, 1000) = 1
    sendfile(8, 9, NULL, 1400)  = 1400
    epoll_wait(6, {{EPOLLOUT, {u32=8, u64=8}}}, 16383, 1000) = 1
    sendfile(8, 9, NULL, 1400)  = 600
    close(9)                    = 0
    epoll_ctl(6, EPOLL_CTL_MOD, 8, {EPOLLIN|EPOLLERR|EPOLLET|0x2000,
    {u32=8, u64=8}}) = 0
    close(8)                    = 0

Yes. That many system calls – I was not kidding when I said that file serving
was added as an afterthought. After some experiments, I’ve managed to turn
that mess into this:

.. code-block:: c

    <... epoll_wait resumed> {{EPOLLIN, {u32=9, u64=9}}}, 16383,
    4294967295) = 1
    read(9, "GET / HTTP/1.0\r\n", 4096) = 16
    newfstatat(7, "index.html", {st_mode=S_IFREG|0664, st_size=13200,
    ...}, 0) = 0
    openat(7, "index.html", O_RDONLY|O_NOATIME) = 10
    sendto(9, "HTTP/1.0 200 OK\r\nContent-Length:"..., 223, MSG_MORE,
    NULL, 0) = 223
    fadvise64(10, 0, 13200, POSIX_FADV_SEQUENTIAL) = 0
    sendfile(9, 10, [0], 13200) = 13200
    close(10)                   = 0

Ah, much better! This was a result of these steps:

1.  Caching the root directory information. This is mainly its
    ``realpath()`` and an open file descriptor to the directory.

    -   The ``realpath()`` result is used with a ``strncmp()`` after so that requests to file outside the root directory are not served successfully. The string length for the root path is also calculated only once.
    -   The astute reader will notice the usage of the Linux-only ``openat()`` and ``newfstatat()`` system calls. These ``-at()`` variants perform much like their standard ones, but they work relative to the directory pointed to the file descriptor passed as the first parameter, avoiding some expensive path-to-inode conversions.

2.  Using ``sendto()`` with ``MSG_MORE`` flag instead of using
    ``TCP_CORK`` flag. This makes for two less roundtrips to the kernel to
    set a socket option.
3.  Using ``sendfile()`` with the whole file instead of sending it in
    chunks, to avoid coroutine context switches. ``sendfile()`` might still
    block, but in this case, the coroutine will yield and the next time, try
    to send a smaller chunk.
4.  The ``-at()`` version of system calls are also being used by a
    replacement ``realpath()`` routine that I’ve adapted from `glibc`_. This
    improved the performance as well by not only reducing the number of
    system calls (the standard ``realpath()`` will perform a ``lstat()`` for
    every path component, whereas this version will only perform
    ``newfstatat()`` for relative components), but also using the lighter
    ``-at()`` variants.

These improvements resulted in *very low overhead* while serving files. In
fact, compared to a simple *hello world* handler and file serving – without
keep-alive – the performance drop even comparing the I/O involved is about
5%.

.. _lwan: http://github.com/lpereira/lwan
.. _glibc: http://www.gnu.org/software/libc/



.. author:: default
.. categories:: none
.. tags:: strace,lwan,programming,C,linux
.. comments::