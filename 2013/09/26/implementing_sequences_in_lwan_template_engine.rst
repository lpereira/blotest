Implementing sequences in lwan template engine
==============================================

When I wrote about lwan's templating engine on a `blog post`_ last year, I
purposedly ommitted the fact that it didn't support sequences. Took me
almost a year, but I've finally implemented it this week. (Lwan is usually a
low priority weekend project. Maybe that should do as an excuse for my
lazyness.)

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
And it does work like a charm.  Here's how to use it.

First, the structure to hold the template variables should be defined:

.. code-block:: c

    struct file_list {
	const char *path;
     
        struct {
          lwan_tpl_generator_t generator; /* TPL_VAR_SEQUENCE macro assumes this exists! */
          const char *name;
        } list;
    };

Then, the descriptors for these variables are written:

.. code-block:: c

    lwan_var_descriptor_t lst_item_desc[] = {
        TPL_VAR_STR(struct file_list, list.name),
        TPL_VAR_SENTINEL
    };
    lwan_var_descriptor_t main_desc[] = {
        TPL_VAR_STR(struct file_list, path),
        TPL_VAR_SEQUENCE(struct file_list, list, dir_list_generator, lst_item_desc),
        TPL_VAR_SENTINEL
    };

Last but not least, the generator function. Just one function will initialize,
keep state, iterate, and clean up after itself.

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

When rendering the template, the engine will create a coroutine whenever it
finds an `{{#list}}` template tag (notice `list` is the name of the inner
struct in `struct file_list`).  This coroutine will be resumed (the first
time this means it'll actually run for the first time, and if the
`opendir()` call succeeds, it will yield a non-zero value.  This means that
the engine will then apply everything until it finds the corresponding
`{{/list}}` tag.  When that happens, it will resume the coroutine again.  On
a non-zero value, it will apply everything again from the `{{#list}}` tag. 
If a zero value is returned, the coroutine is freed and the template engine
proceeds.  Did I mention I like Rube Goldberg machines?

In an ideal world, one would use something akin to Golang's `Channels`_, but
if I were to implement them in lwan it would take another year.  Plus, they
wouldn't be as efficient as setting some pointers.

(As always, the code is available on my `Github`_.)

.. _`Github`: https://github.com/lpereira/lwan
.. _`Channels`: http://golang.org/doc/effective_go.html#channels
.. _`Rube Goldberg machine`: https://en.wikipedia.org/wiki/Rube_Goldberg_machine
.. _`blog post`: http://tia.mat.br/blog/html/2012/11/11/mustache_templates_in_c.html
.. _`coroutine stuff`: http://tia.mat.br/blog/html/2012/09/29/asynchronous_i_o_in_c_with_coroutines.html


.. author:: default
.. categories:: none
.. tags:: C,lwan,programming
.. comments::
