Initializing a heap-allocated structure in C
============================================

A pretty common mistake that happens when programming things in C is to
allocate less memory than necessary to hold a structure:

.. code-block:: c

	struct foobar *foobar = malloc(sizeof(struct foobaz));

Note that ``struct foobaz`` is passed instead of ``struct foobar``. We might get
lucky, and ``sizeof(struct foobaz)`` might be larger or equal than
``sizeof(struct foobar)``, but we might not.

There are lots of tools out there that will catch these mistakes: static
analyzers such as the one from Clang, and Memcheck from Valgrind are just
two examples that should be in any C programmer's toolbelt.

Even then, people often resort to a a nicer idiom: ``sizeof(*foobar)``,
which not only avoids these problems, but also is somewhat future-proof,
should the type of ``foobar`` change:

.. code-block:: c

	struct foobar *foobar = malloc(sizeof(*foobar));

However, structures often have members that, if someone forgets to
initialize, will inflict some unintialized behavior pains on the user.  The
things in the toolbelt might help here, as well as the ``calloc()``
function, that, in addition to allocating memory, also zero-out the memory
block:

.. code-block:: c

	struct foobar *foobar = calloc(1, sizeof(*foobar));

Not always one would want to zero out the whole memory chunk just to fill
out important fields afterwards, though.

Here's a trick that's being used in a yet-to-be-released project I've been
working on and off for the past few months. It starts by defining the
generic-chunk-of-memory equivalent of ``strdup()``, ``memdup()``:

.. code-block:: c

	void *memdup(const void *src, size_t sz) {
		void *mem = malloc(sz);
		return mem ? memcpy(mem, src, sz) : NULL;
	}

Then a macro is defined:

.. code-block:: c

	#define ALLOC_INIT(type, contents)	\
		memdup(&(type) contents, sizeof(type))

Then it is used like so:

.. code-block:: c

	struct foobar *foobar = ALLOC_INIT(struct foobar, {
		.field = value,
		.other_field = other_value,
		.yet_another_field = yet_another_value
	});

The compiler will check if ``field``, ``other_field``, and ``yet_another_field``
are actually part of ``struct foobar``, and will abort compilation of a field
isn't there or is of the wrong type.

The amount of memory allocated will be exactly what's needed by the
structure, and all fields that not mentioned will be initialized with their
default values as per named initializer rules.

If ``memdup()`` is inlined, a good compiler will generate pretty good code,
that's often byte-by-byte equivalent to allocating directly with
``malloc()``, initializing all the fields by hand, etc.

It's a pretty nice idiom that I haven't seen anywhere else, and I'm blogging
here as the project I'm working on might not ever see the light of day and
it would be a shame if at least this didn't become public.


.. author:: default
.. categories:: none
.. tags:: C, programming, trick
.. comments::
