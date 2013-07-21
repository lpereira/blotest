Partial Functions in C
======================

There are some functions in the standard C library that takes a function
pointer to be used as a callback later on.  Examples include ``atexit()``
and ``signal()``.  However, these functions can't receive an arbitrary
pointer (which could hold some important program state) in addition to the
function pointer, so you're left with pesky global variables.

I've devised a workaround, which I'll explain below. I believe the overall
mechanism to be quite interesting, however I do not recommend its usage. Not
only because the implementation wastes a whole memory page for a callback,
but also because I don't want to encourage people to perpetuate this kind of
take-pointer-to-function-without-argument nonsense.

I'll begin with the template function. The idea is to have a function whose
code can be patched up later -- however that code turns out to be generated
by the compiler:

.. code-block:: c

    #define PARAMETER_CONSTANT 0xFEEDBEEF
    #define FUNCTION_CONSTANT 0xABAD1DEA

    static void
    partial_template_function(void)
    {
        ((void (*)(void *))FUNCTION_CONSTANT)((void *)PARAMETER_CONSTANT);
    }

The funky-looking cast basically says "call a function pointer at
``FUNCTION_CONSTANT`` with a pointer pointing to ``PARAMETER_CONSTANT``". Of
course, if you call this code as is, the program will crash (unless you're
very fortunate to some executable code in ``0xABAD1DEA``, of course). The
idea is that this generates this code (IA32 assembly):

.. code-block:: objdump

    0f00deba <partial_template_function>:
       0:    55                       push   %ebp
       1:    89 e5                    mov    %esp,%ebp
       3:    83 ec 18                 sub    $0x18,%esp
       6:    c7 04 24 ef be ed fe     movl   $0xfeedbeef,(%esp)
       d:    b8 ea 1d ad ab           mov    $0xabad1dea,%eax
      12:    ff d0                    call   *%eax
      14:    c9                       leave  
      15:    c3                       ret  

Even if you don't know assembly, you can clearly see the constants in the
code. By writing a trivial function to patch these magic values to something
useful (such as a real function or some real pointer argument):

.. code-block:: c

  static bool
  patch_pointer(void *code_addr, size_t code_len, void *look_for, void
  *patch_with)
  {
      unsigned char *code = code_addr;
      intptr_t look = (intptr_t)look_for;
   
      do {
          if (*((intptr_t *)code) == look) {
              union {
                unsigned char octet[sizeof(void *)];
                void *ptr;
              } patch;
   
              patch.ptr = patch_with;
              code[0] = patch.octet[0];
              code[1] = patch.octet[1];
              code[2] = patch.octet[2];
              code[3] = patch.octet[3];
   
              return true;
          }
   
          code++;
      } while (code_len--);
   
      return false;
  }

And using it to patch the pointers in a page allocated with `mmap()`
(comments and error recovery have been ommitted for brevity; full source
code is linked below):

.. code-block:: c

  struct Partial *
  partial_new(void (*func)(void *data), void *data)
  {
      struct Partial *t;
   
      if (!func) return NULL;
   
      t = calloc(1, sizeof(*t));
      t->caller_len = (size_t)((intptr_t)partial_new - (intptr_t)partial_template_function);

      t->caller = mmap(0, t->caller_len, PROT_WRITE | PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
   
      memcpy(t->caller, partial_template_function, t->caller_len);
   
      patch_pointer(t->caller, t->caller_len, (void *)FUNCTION_CONSTANT, func);
      patch_pointer(t->caller, t->caller_len, (void *)PARAMETER_CONSTANT, data);
   
      mprotect(t->caller, t->caller_len, PROT_EXEC | PROT_READ);
   
      return t;   
  }


The end result will be a function that can be called without arguments --
which will magically call another function with a given parameter:

.. code-block:: c

  static void
  test(void *data)
  {
      printf("Test called with data=%p\n", data);
  }

  int main(void)
  {
      struct Partial *p;
      void (*func)();

      p = partial_new(test, (void *)0x12341337);
      func = partial_to_function(p);

      atexit(func);

      return 0;
  }


Which, when executed, will print:

.. code-block:: console

  [leandro@navi]$ ./a.out
  Test called with data=0x12341337


Useful? Hardly. Interesting? I think so. Fun? Yup.

If you'd like to try, the full source code, with comments and error recovery
is available in this `gist`_.


.. _gist: https://gist.github.com/lpereira/5062388

.. author:: default
.. categories:: none
.. tags:: c,trick,programming
.. comments::
