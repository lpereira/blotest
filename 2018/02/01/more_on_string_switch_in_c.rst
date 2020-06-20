More on string switch in C
==========================

Talking about uncommon programming tricks the other day, the subject of
switching on strings in C appeared on the table.

If you follow this blog, you know it's something `actually possible to do
with a little bit of ingenuity
</posts/2012/08/09/string_switch_in_c.html>`_; in fact, it's one of the
things that I use in Lwan to parse the HTTP requests.  I didn't spend too
much time in that blog post to explain why it is faster, so I'm rectifying
this now.

In order to understand why it's so fast, let me step aside for a moment and
show a function every C programmer should be able to write: ``strlen()``.

.. code-block:: c

	size_t strlen(const char *s) {
	    size_t len = 0;

	    while (*s != '\0') {
		len++;
		s++;
	    }

	    return len;
	}

Style issues aside, this is pretty much the simplest way to implement this
function.  And, maybe the one that generates the slowest code.  There are
many reasons here, so let's explore some of them.

One of them is that CPUs are able to fetch more than a single byte at a time
from memory (or cache).  And it takes roughly the same time for it to fetch
8 bits than it takes to fetch 32 bits.  People that write C libraries know
about this fact, so that the version that your operating system provides is
most likely going to exploit this.  Let's rewrite the ``strlen()`` function,
then:

.. code-block:: c

	size_t strlen(const char *s) {
	    size_t len = 0;

	    while (true) {
		uint32_t v = *(uint32_t *)s;

		if ((v & 0xff) == '\0') return len;
		if (((v >> 8) & 0xff) == '\0') return len + 1;
		if (((v >> 16) & 0xff) == '\0') return len + 2;
		if (((v >> 24) & 0xff) == '\0') return len + 3;

		len += 4;
		s += 4;
	    }
	}

There is a big issue in this code: it is invoking undefined behavior.  The
explanation of why this is illegal in C will follow, but for now, let's just
assume that the integer cast from a character pointer is valid.

With that assumption in mind, what this program is doing is in fact very
simple: it is reducing the amount of expensive operations (fetching things
from memory), and is increasing the amount of cheap operations (masking bits
and comparing integers).  In fact, that's a recurring theme whenever you're
trying to optimize any algorithm: the computer can't run a piece of code faster,
but you can make the computer run smarter code that produces the same output.

This program, however, will most likely crash on some platforms, or be
really slow on others.  The reason is that it is trying to read a pointer
that is not aligned.  Some CPU designers decided to increase the complexity
and perform more work behind the scenes to make this work, and some decided
it wasn't worth the trouble and will just generate an exception.  The major
problem, however, is that this is precisely the undefined behavior I was talking
about.  So, let's fix this function, by modifying it slightly so that the fast
path operates on aligned pointers:

.. code-block:: c

	static inline bool is_ptr_aligned(const void *ptr) {
	    uintptr_t p = (uintptr_t)ptr;

	    /* Assuming a 32-bit machine with 4-byte alignment for
	     * integers.  Executing "AND (n - 1)" is equivalent to "MOD
	     * (n)", without an expensive division operation; this is
	     * true for every (n), as long as (n) is a power of 2.
	     * Compilers can do this optimization on constant values,
	     * but I prefer to be explicit. */
	    return (p & 0x3) == 0;
	}

	size_t strlen(const char *s) {
	    size_t len = 0;

	    /* Read one byte at a time until the pointer is aligned. */
	    while (!is_ptr_aligned(s)) {
		if (*s == '\0')
		    return len;
		s++;
		len++;
	    }

	    /* Pointer is aligned, try the faster version now. */
	    while (true) {
		uint32_t v = *(uint32_t *)s;

		if ((v & 0xff) == '\0') return len;
		if (((v >> 8) & 0xff) == '\0') return len + 1;
		if (((v >> 16) & 0xff) == '\0') return len + 2;
		if (((v >> 24) & 0xff) == '\0') return len + 3;

		len += 4;
		s += 4;
	    }
	}

There is still an even faster way, that is to improve the way the NUL byte
is found in a word.  The excellent (and one of my favorite websites) "`Bit
Twiddling Hacks
<https://graphics.stanford.edu/~seander/bithacks.html#ZeroInWord>`_" web
page has a method to find out if a word contains a NUL byte; it doesn't tell
which byte is the NUL byte, but we don't need to know that in the fast path:

.. code-block:: c

	size_t strlen(const char *s) {
	    size_t len = 0;
	    uint32_t v;

	    /* Read one byte at a time until the pointer is aligned. */
	    while (!is_ptr_aligned(s)) {
		if (*s == '\0')
		    return len;
		s++;
		len++;
	    }

	    /* Pointer is aligned, try the faster version now. */
	    while (true) {
		v = *(uint32_t *)s;

		/* Use a fast bit twiddling hack to find if the
		 * next 4 bytes in the string has a 0 byte. If
		 * it does, find out which byte it is. */
		if ((v - 0x01010101) & ~v & 0x80808080)
		    break;

		len += 4;
		s += 4;
	    }

            if ((v & 0xff) == '\0') return len;
            if (((v >> 8) & 0xff) == '\0') return len + 1;
            if (((v >> 16) & 0xff) == '\0') return len + 2;

	    return len + 3;
	}

Another thing to consider in these functions is that they're not endian
neutral.  A decent implementation would ensure that it would work both on
little-endian and on big-endian machines.  A decent programmer would even
build and test these; I didn't.

Yet another thing to consider is that hand-tuned assembly versions, most
likely written to make use of vector instructions, are the ones that your
computer are executing at this very instant; but they all draw from these
very same ideas: read memory less often, compare in bulk.

Also, there are most likely better ways to write these functions, even without
vector instructions.  But this is besides the point of explaining why the
string switch trick works so well.

Now, this kind of optimization happens on pratically all string handling functions
in the C standard library.  And functions that perform substring comparison,
such as ``strncmp()``, are no exception.

When faced with the necessity to check for a bunch of strings, the idiomatic
C way of doing so would be the following:

.. code-block:: c

	if (!strncmp(s, "GET ", 4))
	    return HTTP_METHOD_GET;
	if (!strncmp(s, "POST ", 5))
	    return HTTP_METHOD_POST;
	if (!strncmp(s, "DELETE ", 7))
	    return HTTP_METHOD_DELETE;
	if (!strncmp(s, "HEAD ", 5))
	    return HTTP_METHOD_HEAD;
	/* ... */
	return HTTP_METHOD_UNKNOWN;

It's not difficult to imagine that each invocation of ``strncmp()`` would have to
do things that are similar to what our toy ``strlen()`` implementation had to do:
align the pointer (which is slow) before it could start the fast path.  But, in
this case, things are even worse, because, if the pointer isn't aligned, it
might not even get to the point where the fast path will make sense, because the
strings it is comparing against are very close to the alignment of the word
size for this computer!

So, to recap, what the string switch does is the following:

.. code-block:: c

	static inline uint32_t string_to_uint32(const char *s) {
	    uint32_t v;

	    memcpy(&v, s, sizeof(v));

	    return v;
	}

	#define STRING_SWITCH(s) switch (string_to_uint32(s))
	#define MCC(a, b, c, d) ((a) << 24 | (b) << 16 | (c) << 8 | (d))
	enum {
	    METHOD_GET = MCC('G', 'E', 'T', ' '),
	    METHOD_POST = MCC('P', 'O', 'S', 'T'),
	    METHOD_DELETE = MCC('D', 'E', 'L', 'E'),
	    METHOD_HEAD = MCC('H', 'E', 'A', 'D'),
	    /* ... */
	};

	STRING_SWITCH(s) {
	case METHOD_GET:
	    return HTTP_METHOD_GET;
	case METHOD_POST:
	    return HTTP_METHOD_POST;
	case METHOD_DELETE:
	    return HTTP_METHOD_DELETE;
	case METHOD_HEAD:
	    return HTTP_METHOD_HEAD;
	/* ... */
	default:
	    return HTTP_METHOD_UNKNOWN;
	}

The good thing about the switch statement in C is that it is maybe the
highest level statement in the language: the compiler can get really
creative in how its code is generated.  It's not uncommon for it to generate
jump tables or even binary searches.  So this implementation would actually
be faster than the various calls to ``strncmp()`` because:

1. Comparing integers is dirt cheap.

2. The compiler knows what ``memcpy()`` does, so it's very likely that on
   architectures where unaligned memory access is fine and there's no
   performance penalty (any Intel Core CPU after Sandy Bridge for instance),
   it'll be just a regular old MOV instruction when the size is small
   and known at compile time.

3. Even if the compiler didn't know what ``memcpy()`` does, it would only
   fill a register once, by doing potentially expensive byte-by-byte copies
   because of unaligned pointer access, and then proceed to just compare
   integers.

4. There is less function call overhead; specially nice since this is
   most likely not going through the PLT.

5. The compiler can reorder the comparisons as it see fit, often producing
   very tight code.

These kinds of micro-optimizations don't necessarily have to be completely
unreadable and full of magical constants.

.. author:: default
.. categories:: none
.. tags:: lwan, programming, trick, C, _featured
.. comments::
