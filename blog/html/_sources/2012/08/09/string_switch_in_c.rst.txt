String switch in C
==================

C’s ``switch`` statement is very powerful. However, it can’t be used with
strings, only with constant integral types. This is understandable, since
strings in C are merely arrays – they’re not first-class citizens.

There are cases where such statement would be useful for strings. Here’s a
trick I’m employing in `lwan`_ to avoid calling the ``strcmp`` family of
functions in some hot paths. This exploits the notion that strings are just
an array of bytes – and by casting them to a pointer to a 32-bit integer, and
dereferencing this pointer, we’ll be able to perform a switch statement on
very small strings (such as file extensions, which are usually comprised of
four characters, including the dot).

C also supports multicharacters integral constants. However, because of
endianess concerns, GCC warns by default when ``-Wall -Wextra`` is used with
these constants. My solution was to just use a macro in conjuntion with an
``enum``, to create the constant integral types expected by the compiler.

The code below, copied directly from `lwan`_, illustrates an usage of this
``STRING_SWITCH`` statement:

.. code-block:: c

    #define STRING_SWITCH_L(s) switch (*((int32_t *)(s)) | 0x20202020)
    #define MULTICHAR_CONSTANT(a,b,c,d) ((int32_t)((a) | (b) << 8 | (c)
    << 16 | (d) << 24))

    enum {
        EXT_JPG = MULTICHAR_CONSTANT_L('.','j','p','g'),
        EXT_PNG = MULTICHAR_CONSTANT_L('.','p','n','g'),
        EXT_HTM = MULTICHAR_CONSTANT_L('.','h','t','m'),
        EXT_CSS = MULTICHAR_CONSTANT_L('.','c','s','s'),
        EXT_TXT = MULTICHAR_CONSTANT_L('.','t','x','t'),
        EXT_JS  = MULTICHAR_CONSTANT_L('.','j','s',0),
    } lwan_mime_ext_t;

    const char* lwan_determine_mime_type_for_file_name(char *file_name)
    {
        char *last_dot = strrchr(file_name, '.');
        if (UNLIKELY(!last_dot))
            goto fallback;

        STRING_SWITCH_L(last_dot) {
        case EXT_CSS: return "text/css";
        case EXT_HTM: return "text/html";
        case EXT_JPG: return "image/jpeg";
        case EXT_JS:  return "application/javascript";
        case EXT_PNG: return "image/png";
        case EXT_TXT: return "text/plain";
        }

    fallback:
        return "application/octet-stream";
    }


Note that ``STRING_SWITCH_L`` performs a bitwise OR with the 32-bit integral
value – this is a fast means of lowering the case of four characters at once.

This kind of switch statement is used in `lwan`_ to match HTTP headers and
HTTP methods, and also the naïve file extension to MIME-Type conversion code
shown above.

.. _lwan: http://github.com/lpereira/lwan



.. author:: default
.. categories:: none
.. tags:: trick,C,programming,lwan
.. comments::