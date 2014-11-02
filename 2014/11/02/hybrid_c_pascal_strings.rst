Hybrid C/Pascal Strings
=======================

I've been thinking for a while on how to reduce the overhead in `Lwan`_'s
string buffer, when the strings are small. There are a number of
ways of accomplishing this.

.. _`Lwan`: http://lwan.ws

A somewhat common way is what ``std::string`` does: it reuses the bits
reserved for `effective string length`, `allocated buffer size`, and
`pointer to buffer` to store the string contents inline.

A `clever improvement`_ is, when the string is small, to turn the
`effective string length` counter to a `bytes remaining counter`, and
put it after the buffer that's storing the string; this way, when the
string is at full capacity, this serves as a ``\0`` terminator, which
is very useful for compatibility with C.  And, of course, as a result,
one more byte can be stored in that string.

.. _`clever improvement`: http://tulrich.com/rants-2009.html#d2009-01-03T00:00:00Z

Another common approach are the strings used in `Pascal`_, where the first
byte tells the length of the string. This has the advantage of allowing
strings to contain ``\0``, but the disadvantage of limiting the maximum
size of the string. If someone were to implement this in C, the
advantage would turn into a disadvantage, as most string-handling
routines present in the standard library would be then rendered useless.

.. _`Pascal`: https://en.wikipedia.org/wiki/String_(computer_science)#Length-prefixed

Or would it?

I'm sure I'm not the first person to come up with the idea of having a
C/Pascal String hybrid.  But at least the `Wikipedia`_ article on
Strings doesn't seem to mention this variant I just came up with:

.. _`Wikipedia`: https://en.wikipedia.org/wiki/String_(computer_science)

* Keep the ``\0`` to terminate the string. This helps reusing the
  string handling routines from the C standard library, which are usually
  very fast, hand-tuned functions
* The first byte tells the size, not in bytes, but in 8-byte blocks.
  To calculate the string length, one just jumps that amount of 8-byte
  blocks and find the position of the ``\0`` terminator.
* Larger blocks could be considered if `SIMD`_ instructions were available.

.. _`SIMD`: https://en.wikipedia.org/wiki/SIMD

With 8-byte blocks, this can yield strings up to 2KiB of size (256 *
8), with an overhead of only two bytes, while retaining compatibility
with C strings.  With SIMD, the maximum string size could be easily
doubled or quadrupled.

Of course, this isn't actually an improvement on the kind of small
string optimization performed by ``std::string``, so I'm not yet
convinced this is the way to go. This is one of the reasons I haven't
yet implemented this, but I might use the fact that I'm currently
enjoying some vacation time and write a prototype.

.. author:: default
.. categories:: none
.. tags:: C,trick,optimization,programming
.. comments::
