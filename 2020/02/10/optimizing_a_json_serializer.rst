Optimizing a JSON serializer (part 1)
=====================================

A few years back, I wrote a `tiny JSON library for the Zephyr OS
<https://tia.mat.br/posts/2017/03/01/parsing_json.html>`__; it focused
mostly in things that are important for an embedded real-time operating
system: code size, type-safety, and predictability (both for memory and CPU
time usage).  It was never tuned to ace performance benchmarks: the other
constraints were far more important driver for its design decisions.

As part of the Lwan entry in the `TechEmpower Web Framework Benchmarks
<https://www.techempower.com/benchmarks/>`__ (TWFB), the `JSON library
<https://github.com/rustyrussell/ccan/tree/master/ccan/json>`__ from CCAN
was used.  It was responsible in part for Lwan `"taking the crown"
<https://www.techempower.com/blog/2015/04/21/framework-benchmarks-round-10/>`__ for that
around, according to their blog post.  It's certainly not a bad library, but
considering I can reason about every line of code in the JSON library I
wrote for Zephyr, I decided to use it instead, moving forward.

I could just consider the JSON library as a black box and not worry about
its guts, but I wanted to optimize it -- just for fun -- and being able to
understand every design decision in the new library contributed a lot to the
decision of changing libraries.

In the end, though, there's not much point in spending time optimizing a
JSON encoder that's good enough already; most of the time is spent in the
network transport, and it's very unlikely that changes in something like
this will actually influence benchmarks.  Lwan is, however, more of a
testbed of ideas, where I'm free to try out different techniques or play
with things I rarely have the opportunity to play with in the "real world",
so this seemed like a good candidate to start.

For those unfamiliar with the JSON benchmark in TWFB, it essentially has the
requirement that, for a particular endpoint, an object is created and
serialized on-the-fly (without caching).  The object has to have the content
(``{"message": "Hello, World!"}``), so unless the JSON library is pretty bad
to begin with, there isn't much that can be done to speed this up.

The CCAN library requires a JSON object tree to be built before
it can serialize, just to require that data to be torn down immediately
afterwards; it is kind of wasteful.  It also requires serializing the whole
JSON buffer into a chunk of memory that's allocated by the encoder,
potentially requiring copies.

The new JSON library, however, takes a different approach.

Instead of requiring an object tree to be built, the serializer traverses a
descriptor array while obtaining values from a user-supplied struct (the
descriptor contains the type and offserts to the user-supplied pointer where
the values can be obtained); it kind of does "manual reflection", if such
thing would make sense.  The struct can be allocated in the stack, avoiding
expensive roundtrips to malloc (and occasional heap fragmentation).  My
`previous blog post about the JSON library
<https://tia.mat.br/posts/2017/03/01/parsing_json.html>`__ has more details
on how this works, from the parsing side.

In addition, the encoder takes a function pointer that's called to append
bytes to a buffer; this interface, inspired by Go's Writer interface,
completely decouples the JSON encoder from the buffer manipulation
facilities.  For the benchmark, since each response in Lwan has a ``struct
lwan_strbuf``, that's what the supplied callback ends up using.  (This
function pointer is also used as a way to calculate the amount of memory
necessary to serialize some piece of data.  More on this later.)

Miscelaneous little improvements
--------------------------------

**Alignment: shift ➡ full values.** Zephyr is built for embedded devices.
Memory is severely constrained, so it's usually fine to pay the price of
packing multiple integer values into a single `uint32_t`.  Lwan doesn't
have that limitation, so bitfields were removed from that version.

**Getting rid of branches while encoding commas between elements:** JSON
uses commas as item delimiter in its collection types; as such, it doesn't
allow trailing commas.  The encoder originally checked if every descriptor
entry was the last item; it was modified to never check if it's the last
item, but rather:

- For objects, is starts looping from the second descriptor element,
  always appending a comma inside the loop; when that's done, the first
  descriptor is serialized.
- For arrays, the loop runs ``(N - 1)`` times, always appending the comma,
  and finally adds the last element.

**Using `int_to_string()` to serialize integers:** the library originally
used ``snprintf()`` to serialize integers.  This is inneficient, `so another
method to convert integers to string
<https://tia.mat.br/posts/2014/06/23/integer_to_string_conversion.html>`__
was used instead.

**Keys don't need to be escaped, most of the time.**  If that's the case,
branches can be removed from the fast path and ``append_bytes()`` can be
called with the key name directly.  This saves a lot of indirect function
calls.   For keys that need to be escaped, or for string values, the
library would previously call ``append_bytes()`` for each byte from the
string to be escaped; it's now batched and only split into multiple calls
if there's a character that needs to be escaped.

**Deferred error checking: ``append_bytes()`` isn't supposed to fail, most of
the time.**  So it's fine to not return early and keep trying to serialize,
as long as the original caller knows that an encoding error happened. So,
instead of many ``err = append_bytes(...); if (err < 0) { return err; }``
lines, the encoder essentially does ``err |= append_bytes(...)`` and returns
``err`` at the end.  This code is not equivalent, especially since
``append_bytes()`` can return any negative error code, but it does remove
alot of branches in the fast path.  If you know your error codes (e.g.
they're all power of two), this can actually be a good solution, and better
than relying on error codes from ``<errno.h>``.

**Pre-encode keys with quotes and colon:** for every key/value pair in an
object, the encoder had to call ``append_bytes()`` at least 5 times: one for
each comma, one for the colon, one for the key, and one for the value.  By
pre-calculating the key+colon in compile time, each key/value pair will
make at most 2 calls to ``append_bytes()``: one for the key, and one for the
value.  This could be easily done in the macros that define a JSON object
descriptor, and stored right after the unencoded key (because each
descriptor also carries the key length with it).

Next time
---------

I'll probably continue working in this JSON library before the next round of
the TWFB takes place.  I'm working on another improvement (that will take
some time to finish) that, if it works, will be described here in the blog. 
(And, of course, next time performance numbers will accompany the article.)

.. author:: default
.. categories:: none
.. tags:: lwan, json, optimization, programming
.. comments::
