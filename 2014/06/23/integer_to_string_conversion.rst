Integer to string conversion
============================

There are various ways to convert integers to their string representation. 
These conversions are rarely a bottleneck, but they often show up while
profiling certain applications.  For instance, they're very common in
`Lwan`_ while building the response headers.

To use Lwan as an example: initially, ``snprintf()`` was used to convert
numbers.  Although this works, it is quite boring, performance-wise.

The second approach was using the naïve algorithm, which basically divides
the number by ``10`` in succession, writing backwards the result of modulus by
``10`` to a string, and then reversing the string when the number reaches ``0``.

.. code-block:: c

    // Code based on https://code.google.com/p/stringencoders/
    size_t naive_uint32_to_str(uint32_t value, char *str) {
        char *wstr = str;
        // Conversion. Number is reversed.
        do
           *wstr++ = (char) decimal_digits[uvalue % 10];
        while (uvalue /= 10);
        *wstr = '\0';
        // Reverse string
        strreverse(str, wstr - 1);
        return wstr - str;
    }

This was fine for a while, but that string reversion step always bothered
me.  Why not just write the string backwards already?

I've then changed the code in Lwan to the following snippet. Note the nice
trick of multiplying the size of an integer in bytes by ``3`` to obtain an
approximation of the number of digits for ``MAX_INT``, including the zero
terminator, regardless of what ``sizeof(int)`` is.

.. code-block:: c

    #define INT_TO_STR_BUFFER_SIZE (3 * sizeof(int))

    char *lwan_uint32_to_str(uint32_t value,
		char buffer[static INT_TO_STR_BUFFER_SIZE],
		size_t *len) {
        char *p = buffer + INT_TO_STR_BUFFER_SIZE - 1;

        *p = '\0';
        do {
            *--p = "0123456789"[value % 10];
        } while (value /= 10);

	size_t difference = (size_t)(p - buffer);
        *len = (size_t)(INT_TO_STR_BUFFER_SIZE - difference - 1;

        return p;
    }

Reducing writes to the array made this algorithm significantly faster. 
However, I eventually did what one should always avoid when tinkering with
this kind of thing: I've changed the array lookup to an addition, without
measuring if it would perform better, and committed the code anyway.  The
lookup table is ~9% faster.  Ouch!

Last year, the Facebook Engineering team `posted a function`_ to convert
integers to strings that manages to be even faster.  They do use the same
idea of avoiding having to reverse the string after they're done converting
each digit, and they use a lookup table as well.

But the nice trick is that, instead of having a lookup table for 10 digits,
there's a table for all pair of digits, from `00` to `99`.  This cuts the
amount of divisions by half, yielding a significantly faster algorithm:
around 31% faster than the above snippet:

.. code-block:: c

    size_t facebook_uint32_to_str(uint32_t value, char *dst)
    {
        static const char digits[201] =
            "0001020304050607080910111213141516171819"
            "2021222324252627282930313233343536373839"
            "4041424344454647484950515253545556575859"
            "6061626364656667686970717273747576777879"
            "8081828384858687888990919293949596979899";
        size_t const length = digits10(value);
        size_t next = length - 1;
        while (value >= 100) {
            auto const i = (value % 100) * 2;
            value /= 100;
            dst[next] = digits[i + 1];
            dst[next - 1] = digits[i];
            next -= 2;
        }
        // Handle last 1-2 digits
        if (value < 10) {
            dst[next] = '0' + uint32_t(value);
        } else {
            auto i = uint32_t(value) * 2; 
            dst[next] = digits[i + 1];
            dst[next - 1] = digits[i];
        }
        return length;
    }

The ``digits10()`` function is also another function that calculates the
number of digits of a number in a very efficient manner.  Even being
performant, though, one can get rid of the call altogether: using a constant
like ``numeric_limits<uint32_t>::digits10`` will keep the same interface. 
This is possible because the ``dst`` buffer should be large enough to hold
all the digits of the largest 32-bit unsigned integer anyway.

Because of implementation details -- the function basically compares numbers
to powers of 10 and recurses when the number of digits surpasses the maximum
power that they're comparing to -- the speedup of using a constant length
won't be significant for small numbers (one and two digits); but if you're
optimizing to this level, using a constant won't hurt.  So much so, that it
is consistently faster on my machine (a Core i7 2640M laptop, with an
up-to-date 64-bit Arch Linux):

.. figure:: https://i.imgur.com/9V0PsPK.png
    :alt: relativespeedup
    :align: center
    :width: 100%

    Relative speedup of ``facebook_uint32_to_str()`` using ``digits10()`` and a
    constant value

That chart was obtained by using a `benchmark program`_ I wrote that will
test all these ways of converting an integer to their string representation. 
To compare with other methods, here's the full chart:

.. figure:: https://i.imgur.com/b2enLNt.png
    :alt: benchmark
    :align: center
    :width: 100%

    Results for ``snprintf()`` omitted to not skew results. Spoiler: it's slow.

Unfortunately, there's a licencing issue that won't let me use this code in
Lwan.  The blog post doesn't mention the license.  I've found this `two-digit
lookup table in places unrelated to Facebook`_ as well, so I'm not sure who
had this idea first.  My go-to source of this kind of thing is usually
`Hacker's Delight`_, but even then it's not there.

.. _`two-digit lookup table in places unrelated to Facebook`: https://mail-archives.apache.org/mod_mbox/apr-dev/200704.mbox/%3C344-65769@sneakemail.com%3E
.. _`Hacker's Delight`: http://www.hackersdelight.org/
.. _`benchmark program`: https://gist.github.com/lpereira/c0bf3ca3148321395037
.. _`posted a function`: https://www.facebook.com/notes/facebook-engineering/three-optimization-tips-for-c/10151361643253920
.. _`Lwan`: http://lwan.ws

.. author:: default
.. categories:: none
.. tags:: lwan,programming,trick,C
.. comments::

