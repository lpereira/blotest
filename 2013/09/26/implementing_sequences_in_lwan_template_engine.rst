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
it to the template engine to render.  Not only cumbersome, but would require
the creation of (potentially) large amounts of temporary objects.

The latter reason lead me to think of a way to implement iterators in C.
This is usually done using callbacks; and although performant, it gets
pretty verbose and tedious as there is usually the need to create structures
to keep state, and different callbacks to initialize, destroy, and advance
the iterator. 

Lots of `things happened since then`_, and this feature sort of creeped
under the low priority rug for the most part of a year.

While writing a completely different program in Python, however, it struck
me: I could use the `coroutine stuff`_ I was already using in lwan and
implement `generator functions`_.  A few minutes later and I had a working
prototype, which can probably better explained with the help of a diagram:

.. image:: http://i.imgur.com/4XF6c3B.png
    :alt: diagram
    :align: center

In short, the engine will create a coroutine whenever it finds a
``{{#sequence}}`` template tag.  This coroutine will start, and will execute
as usual until it yields.

Yielding ``false``, the engine assumes the iteration ended, and proceeds to
find the next matching ``{{/sequence}}`` tag to continue from there.

On a ``true`` yield, however, the engine will recurse to apply everything is
between the iteration tags, repeating the process when the iteration-end tag
is found and the coroutine yields ``true`` again.

The coroutine is supposed to clean up after itself before returning a
``false`` value.

.. figure:: http://i.imgur.com/7P2yadJ.jpg
    :alt: rubegoldbergmachine
    :align: center

    Professor Butts would be proud. Maybe. `Source`_.

A sample generator function is shown below. It iterates over a directory
with ``readdir()``, returning ``1`` on new item availability and ``0`` when there
isn't anything else to do. Notice that initialization, iteration, and cleanup
is all contained within a single function.

Also, notice that there's no need to copy any values to and from the
structure -- calling ``coro_yield()`` will of course maintain the stack
alive, so local variables can be used outside this function as long as a
reference to them can be obtained.

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
buggy, but whatever I could find has been fixed in `HEAD`_ already.)

In an ideal world, one would use something akin to Golang's `Channels`_, but
if I were to implement them in lwan it would take perhaps another year. 
Plus, they wouldn't be as efficient as setting some pointers.  But they
might be useful in the future, so I'm not completely discarding the idea. 
Although I've never written a single line of Go code, I'm reading a lot
about it recently and it is sort of positively impacting the way I think
about programming.  But I digress.

.. _`HEAD`: https://github.com/lpereira/lwan
.. _`Channels`: http://golang.org/doc/effective_go.html#channels
.. _`Rube Goldberg machine`: https://en.wikipedia.org/wiki/Rube_Goldberg_machine
.. _`blog post`: http://tia.mat.br/blog/html/2012/11/11/mustache_templates_in_c.html
.. _`coroutine stuff`: http://tia.mat.br/blog/html/2012/09/29/asynchronous_i_o_in_c_with_coroutines.html
.. _`commit message`: https://github.com/lpereira/lwan/commit/a4188d73a00cec4c99d50473803c44bfb2218d13
.. _`Source`: https://en.wikipedia.org/wiki/File:Rubenvent.jpg
.. _`struct file_list`: https://gist.github.com/lpereira/6694015
.. _`things happened since then`: https://01.org/blogs/imad/2013/welcome-profusion
.. _`generator functions`: https://wiki.python.org/moin/Generators

.. author:: default
.. categories:: none
.. tags:: C,lwan,programming
.. comments::
