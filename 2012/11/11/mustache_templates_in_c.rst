Mustache templates in C
=======================

Generating textual output is a lot easier with templates than it is with
handcrafted functions. And it is a lot easier in languages such as Python,
where things like introspection are easy and cheap. But that doesn’t
necessarily mean we can’t do that in C if we know where to look.

I’ve implemented a subset of `Mustache`_ templates in C that leverages some
tricks that makes template rendering both convenient and efficient. For
instance, if you have a template such as this:

.. code-block:: c

    Hello, {{name}}!

It can easily be rendered with the following code:

.. code-block:: c

    hello_t data = {
      .name = "World"
    };
    lwan_tpl_render(hello, &data);

Where ``hello`` is the template that was previously compiled into a series of
simple instructions (such as **append text** or **append the value of a
variable**), and the second parameter is a structure containing the data
needed by the renderer.

My first thought to render these templates would involve the use of a hash
table. While reasonably efficient (even considering the overhead to create
and destroy the table every time the template had to be rendered), they’re
not first class citizens in C, and the usage would be pretty clumsy, to say
the least:

.. code-block:: c

    hash_table *ht = hash_table_new();
    hash_table_add(ht, "name", "World");

    lwan_tpl_render(hello, ht);

    hash_table_free(ht);

Instead, I’ve decided to go on another road: use standard C structures to
store the values in their native form, and then find a way to lookup these
values whenever necessary to render the template.

The first trick, then, was to use a C99 feature called `compound literals`_,
which is supported by GCC even in C89 mode. This trick allows the use of
`anonymous arrays`_, among other things, and provides enough syntactic sugar
to conveniently group the template variables:

.. code-block:: c

    lwan_tpl_render(hello, (hello_t[]) {{
      .name = "World"
    }});

Without a way to lookup which value to obtain from the structure, however,
this would not help much. Enter the second trick: the ``offsetof(3)`` macro,
which computes the offset of a field in a given structure. By storing this
offset alongside data type information, the value lookup is not only possible
but can also work with types different than strings:

.. code-block:: c

    typedef struct hello_t {
      char *name;
      int age;
    };
    /*
     * The TPL_VAR_??? macros provides some convenience to declare each
     * descriptor. These expand to a declaration containing the name of
     * the variable as a string (used to validate the template during
     * compile time), the field offset, and pointers to functions that
     * convert the values to string and check if they're empty.
     *
     * The SENTINEL type is there so the template compiler knows when to
     * stop looking for descriptors, since of course you can have as
     many
     * fields as necessary.
     */
    lwan_var_descriptor_t hello_descriptor[] = {
      TPL_VAR_STR(hello_t, name),
      TPL_VAR_INT(hello_t, age),
      TPL_VAR_SENTINEL
    };
    lwan_tpl_t *hello;
    strbuf_t *rendered;

    /*
     * ``hello'' would usually be compiled once and kept around for
     * the whole duration of the program.
     */
    hello = lwan_tpl_compile("hello.tpl", hello_descriptor);

    /*
     * Rendering the template then would be just the matter of calling
     * this function, which will output a ``strbuf_t''. The template
     * compiler estimates the starting size of this string buffer, so
     * rendering will incur in very few expensive reallocations, if
     * there are reallocations at all.
     */
    rendered = lwan_tpl_render(hello, (hello_t[]) {{
      .name = "World",
      .age = 42
    }});

    printf("%s\n", strbuf_get_buffer(rendered));
    strbuf_free(rendered);

`Code for this engine`_ is available in the `wip branch`_ of my toy web
server, lwan. It is not currently used there, but it is built alongside the
main program and can be tested by invoking the generated ``template``
executable.

Before using that in lwan, though, I’ll try to employ this `nifty trick`_ to
JIT-compile the template and avoid some of the overhead where it really
matters. While at the same time possibly opening a whole can of worms from
the security standpoint, though – but it wouldn’t be fun without some risk,
would it? :)

.. _Mustache: http://mustache.github.com/
.. _compound literals: http://gcc.gnu.org/onlinedocs/gcc-3.3.1/gcc
    /Compound-Literals.html
.. _anonymous arrays:
    http://www.run.montefiore.ulg.ac.be/~martin/resources/kung-f00.html
.. _Code for this engine:
    https://github.com/lpereira/lwan/blob/wip/template.c
.. _wip branch: https://github.com/lpereira/lwan/tree/wip/
.. _nifty trick: http://dginasa.blogspot.com.br/2012/10/brainfuck-jit-
    compiler-in-around-155.html



.. author:: default
.. categories:: none
.. tags:: lwan,C,tricks,template
.. comments::