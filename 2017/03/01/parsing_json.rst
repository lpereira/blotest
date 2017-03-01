Parsing JSON
============

There are many libraries out there to parse JSON files.  It might be a
futile attempt, then, to write yet another one.  However, when you're
working on a RTOS where memory is golden, and the alternatives don't look
that great, you got to do something about it.

Recently I wrote a `JSON <http://www.json.org>`__ parser for a project at
work.  This parser uses constant memory, regardless of the amount of data
it's working with, and deserializes directly to a C struct.  Similar, in
spirit, to the JSON parser that's part of the Golang standard library, that
encodes and decodes data based on a tagged structure.

The lexer is the usual state machine, where the state itself is a function
pointer to a function that handles that particular state.

I've been using this technique for a while, and I found that it's a very
clean and efficient way of describing state machines, specially for lexers. 

I began using it after a coworker wrote a `parser for a DSL
<https://github.com/solettaproject/soletta/blob/3bda9802b243c2052555cf88263f754d34458414/src/shared/sol-fbp-internal-scanner.c>`__
using it -- and he got the idea from the -- you guessed -- Golang template
package.  (There's a `nice talk by Rob Pike about it
<https://www.youtube.com/watch?v=HxaD_trXwRE>`__ -- I recommend this talk
not only for the lexing goodness, but also for the tips on how to evolve a
concurrent design.)

The parser implementation itself is nothing to write home about.  However,
by using the same idea used in Lwan's mustache template engine to `obtain
the variables
<https://tia.mat.br/posts/2012/11/11/mustache_templates_in_c.html>`__, it
manages to do some things that are not common in JSON parsers written in C:

* It will accept only values of known types for a particular key.
* It will save the decoded value directly in a struct field.
* It won't try to decode the same field twice.

The first point is crucial when working with data received from the network,
which is precisely the kind of thing I'm dealing with.  This avoids problems
such as type confusion and such, and moves the responsibility of checking
the types to the library rather than the user of the library.

By saving the decoded value directly into a struct field, it does use a
predictable amount of memory.  This is good, as it's not going to balloon
out of control, or require some guesswork to know beforehand how many tokens
are going to be necessary to deserialize some values.  The C compiler
already knows exactly how many bytes a struct needs.

Some fields might be optional in a JSON blob.  So the parser uses a bitmask
to mark which fields have been decoded (and returns that, so that the
library user can efficiently test if a value has been deserialized or not). 
Since it was easy to do, the library refuses to decode a key that has been
deserialized before.

So, a typical use is the following:

.. code-block:: c

    /* First, define a struct to hold the values. */
    struct values {
        char *some_string;
        int some_int;
        bool some_bool;
    };

    /* Then, define a descriptor for that struct. */
    static const struct json_descr values_descr[] = {
        FIELD(struct values, some_string, JSON_TOK_STRING),
        FIELD(struct values, some_int, JSON_TOK_NUMBER),
        FIELD(struct values, some_bool, JSON_TOK_TRUE),
    };
    /* (FIELD is just a macro that saves the offsetof()
     * each struct member so that a pointer can be produced
     * afterwards.)  */

    /* It's now just a matter of parsing the JSON now. */
    struct values values;
    int32_t ret = json_parse(serialized, strlen(serialized),
	values_descr, ARRAY_SIZE(values_descr), &values);

    /* Bits 0, 1, and 2 of ret will be set if some_string,
     * some_int, and some_bool have been successfully
     * deserialized.  */

Another thing that could be done -- but that has not been implemented yet,
is to do the opposite as well: the descriptor and a struct to produce
JSON-encoded data.  This has many advantages over the usual JSON libraries
that require generating a JSON tree in memory just to serialize it
afterwards.

And although I'm quite happy with this code, there are still some
limitations that I'll address whenever I have the need.

Mainly, there's no way to parse nested objects or arrays.  I've written code
to do this but these changes haven't gotten any fuzz-testing action so I'm
holding them off it until my living room heater^Wcomputer has worked on the
problem for at least a week.

Another one that's not a deal breaker for an embedded OS is the lack of
floating pointing numbers (only integers for now).  Parsing floating point
is `trickier than it sounds <http://www.netlib.org/fp/dtoa.c>`__, and
there's no ``strtod()`` in Zephyr's minimal libc.

As a minor issue to work around, there's the return value: this limits the
number of fields to be parsed to 32; that should be plenty for most uses. 
However, in the unlikely event that's not sufficient, this can be worked
around by having multiple descriptors.

And, finally, there's the JSON encoding part that I've mentioned already.

The major problem with this piece of code, that can't be fixed by writing
more code, is that I can't use it with Lwan due to licensing reasons:
although it is open source, part of the `Zephyr project
<http://www.zephyrproject.org>`__, it is licensed under the Apache 2
license, which is incompatible with the GPL2+ used by Lwan (would have to
bump it to [L]GPL3).

(For those that might ask how fast is it: it's fast enough. I didn't
measure, I didn't compare, and I don't really care: it's readable,
maintainable, and does the job.)

.. author:: default
.. categories:: none
.. tags:: programming, zephyr, parser
.. comments::
