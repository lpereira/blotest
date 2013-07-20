Deferred statements in C
========================

`Golang`_ has a lot of nice features – and one I found pretty interesting is
called `deferred statements`_. This can be implemented in C++ pretty easily
through `RAII`_, but in C we’re pretty much out of luck. Or are we?

In `lwan`_, I’m using my own home-cooked `coroutine`_ implementation. All
requests are handled by coroutines, so that it makes easy to condition the
execution of deferred statements with the cleanup of a coroutine. And that’s
what I did, by implementing ``coro_defer()``, which adds hooks that will be
called sequentially by ``coro_free()``.

This can be used for various purposes, including garbage collection and other
miscellaneous cleanup code:

.. code-block:: c

    void* coro_malloc(coro_t *coro, size_t sz) {
        void *ptr = malloc(sz);
        if (ptr)
                coro_defer(coro, free, ptr);
        return ptr;
    }

    void* coro_strdup(coro_t *coro, const char *str) {
        char *dup = strdup(str);
        if (dup)
                coro_defer(coro, free, ptr);
        return dup;
    }

    int coro_open(coro_t *coro, const char *path, int flags)
    {
        int fd = open(path, flags);
        if (fd >= 0)
                coro_defer(coro, close, INT_TO_PTR(fd));
        return fd;
    }


This way, one can easily allocate memory, lock mutexes, open files – and
leave the cleanup to `lwan`_.

.. _Golang: http://golang.org
.. _deferred statements: http://blog.golang.org/2010/08/defer-panic-and-
    recover.html
.. _RAII:
    https://en.wikipedia.org/wiki/Resource_Acquisition_Is_Initialization
.. _lwan: http://github.com/lpereira/lwan
.. _coroutine: https://en.wikipedia.org/wiki/Coroutine



.. author:: default
.. categories:: none
.. tags:: trick,lwan,programming,C
.. comments::