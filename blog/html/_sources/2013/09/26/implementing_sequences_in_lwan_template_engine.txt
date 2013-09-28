Implementing sequences in lwan template engine
==============================================

When I wrote about lwan's templating engine on a `blog post`_ last year, I
purposedly ommitted the fact that it didn't support sequences. Took me
almost a year, but I've finally implemented it this week. (Lwan is usually a
low priority weekend project. Maybe that should do as an excuse for my
laziness.)

It took me three tries to get this right. `Rube Goldberg machine`_ kind of
right, but there's always some elegance in ingenuity.

The first try would require one to create the list beforehand, and then pass
it to the template engine to render. Not only cumbersome, but would require
the creation of (potentially) large amounts of temporary objects.

The latter reason lead me to think of a way to implement iterators in C.
This is usually done using callbacks; and although performant, it gets
pretty verbose and tedious as there is usually the need to create structures
to keep state, and different callbacks to initialize, destroy, and advance
the iterator.

While writing a completely different program in Python, it struck me: I
could use the `coroutine stuff`_ I was already using in lwan and implement
generator functions.  A few minutes later and I had a working prototype. 
And it does work like a charm.

The following diagram might help understand how this contraption works.

.. image:: http://i.imgur.com/4XF6c3B.png
    :alt: diagram
    :align: center

When rendering the template, the engine will create a coroutine whenever it
finds an `{{#list}}` template tag (notice `list` is the name of the inner
struct in `struct file_list`).  This coroutine will be resumed (the first
time this means it'll actually run for the first time, and if the
`opendir()` call succeeds, it will yield a non-zero value.  This means that
the engine will then apply everything until it finds the corresponding
`{{/list}}` tag.  When that happens, it will resume the coroutine again.  On
a non-zero value, it will apply everything again from the `{{#list}}` tag. 
If a zero value is returned, the coroutine is freed and the template engine
proceeds.


.. figure:: http://i.imgur.com/7P2yadJ.jpg
    :alt: rubegoldbergmachine
    :align: center

    Professor Butts would be proud. `Source`_.

A sample generator function is shown below. This one opens a directory,
yields for every entry, close the directory and finally yields 0, telling
the template engine to clean the state and continue rendering.  The same
idea could be used to fetch rows from a database query, for instance, and the
template syntax would remain unchanged.

.. code-block:: c

    int dir_list_generator(coro_t *coro)
    {
        DIR *dir;
        struct dirent *ent;
        struct file_list *fl = coro_get_data(coro);
     
        dir = opendir(fl->path);
        if (!dir)
          return 0;
     
        while ((ent = readdir(dir))) {
          fl->list.name = ent->d_name;
          coro_yield(coro, 1);   /* !0 means "iter not done yet" */
        }    
     
        closedir(dir);
        return 0;
    }

The details of how the variable descriptors are set up are explained in the
`commit message`_ that introduced this change.  (The commit itself is quite
buggy, but whatever I could find has been fixed in `HEAD` already.)

In an ideal world, one would use something akin to Golang's `Channels`_, but
if I were to implement them in lwan it would take perhaps another year. 
Plus, they wouldn't be as efficient as setting some pointers.

(As always, the code is available on my `Github`_.)

.. _`Github`: https://github.com/lpereira/lwan
.. _`Channels`: http://golang.org/doc/effective_go.html#channels
.. _`Rube Goldberg machine`: https://en.wikipedia.org/wiki/Rube_Goldberg_machine
.. _`blog post`: http://tia.mat.br/blog/html/2012/11/11/mustache_templates_in_c.html
.. _`coroutine stuff`: http://tia.mat.br/blog/html/2012/09/29/asynchronous_i_o_in_c_with_coroutines.html
.. _`commit message`: https://github.com/lpereira/lwan/commit/a4188d73a00cec4c99d50473803c44bfb2218d13
.. _`Source`: https://en.wikipedia.org/wiki/File:Rubenvent.jpg

.. author:: default
.. categories:: none
.. tags:: C,lwan,programming
.. comments::
