Converting GW-BASIC to the Z80
==============================

.. tags:: programming, z80, assembly, retrocomputing

Right after the BUILD conference, Microsoft `released the source code
for the first version of GW-BASIC for the MS-DOS under the MIT license
<https://devblogs.microsoft.com/commandline/microsoft-open-sources-gw-basic/>`_.
Not only this is an improved version of the very first product that
kickstarted the company, it's also the base for my first programming
language, the MSX Basic.

.. code:: plain

    COMMENT *

    --------- ---- -- ---- ----- --- ---- -----
    COPYRIGHT 1975 BY BILL GATES AND PAUL ALLEN
    --------- ---- -- ---- ----- --- ---- -----

    ORIGINALLY WRITTEN ON THE PDP-10 FROM
    FEBRUARY 9 TO  APRIL 9 1975

    BILL GATES WROTE A LOT OF STUFF.
    PAUL ALLEN WROTE A LOT OF OTHER STUFF AND FAST CODE.
    MONTE DAVIDOFF WROTE THE MATH PACKAGE (F4I.MAC).

    *

Needless to say, I was stoked to see this release, and decided to take
a look -- it's a historic artifact that's very close to home.  To my
surprise, I noticed that many of the comments were referencing the
Intel 8080 registers and not the Intel 8086 registers.  The reason for
this is that these sources were translated mechanically by a tool written
in the 80s; that's why there were many versions of the Microsoft BASIC
for home computers in that era, despite the variety in CPU architectures
of the era.

.. code:: asm

    ;
    ; FIND A "FOR" ENTRY ON THE STACK WITH THE VARIABLE POINTER
    ; PASSED IN [D,E].
    ;
    PUBLIC  FNDFOR
    FNDFOR: MOV     BX,OFFSET 4+0   ;IGNORING EVERYONES "NEWSTT"   
                                    ;AND THE RETURN ADDRESS OF THIS
            ADD     BX,SP           ;SUBROUTINE, SET [H,L]=SP

(Note in the fragment above that ``BX`` is used as instruction arguments,
although ``H`` and ``L`` are referenced in the comment.  It also mentions
``D`` and ``E``, which are Z80/8080 registers.  This kind of comment was
helpful in determining the register mapping between 8086 and Z80.  More
details below.)

All assembly source files contain a comment in the first line referencing
this instruction set conversion tool, which wasn't unfortunately open
sourced (for reasons I don't know):

.. code:: asm

    ; [ This translation created 10-Feb-83 by Version 4.3 ] 

Naturally, this intrigued me and I decided to port this back to the Z80
(which is compatible, on a machine code level, with the Intel 8080), with
the intention of running it on a `MSX <https://en.wikipedia.org/wiki/MSX>`_
(or a `RC2014 <https://rc2014.co.uk/>`_).  And, of course, instead of converting
the whole source code from 8086 assembly into Z80 assembly, I decided to write
a tool to perform (most) of the conversion for me.

Although my first computer had a Z80 processor, I never had a chance to
actually write any Z80 code; so this has been an interesting experience.
Luckily, I played quite a bit with the MS-DOS ``debug.com``, so some things,
such as the 8086 segmented memory model, wasn't that alien to me.

The Conversion Tool
===================

The conversion tool works pretty much like a compiler.

It's written in Python and is set up as a pipeline, with 4 components: the
lexer, the parser, the transformer, and the writer.  (I'm currently
refactoring the converter to have 4 components, that will sit between the
transformer and the writer, and which sole purpose will be to transform 8086
tokens into Z80 tokens, in such as way that it's consistent and
error-checked.)

Each component is a generator, yielding a token whenever they're done munching
their input.

Lexer
-----

The lexer works in a way that's very similar to `the way I've been writing lexers for
quite a while now </posts/2017/03/01/parsing_json.html>`_, so there's not much surprise
there.

Parser
------

The parser is a traditional recursive descent parser.  It's a trivial implementation
for one, but there's quite a bit of logic to handle some special cases found only in
the GW-BASIC code base.  Mainly, a Python implementation of the ``MOVRI`` and ``INS86``
macros:

- The ``INS86`` macro is used to generate assembly instructions that were
  either not supported by the assembler used at the time.  It's heavily used
  throghout the code base, with over 120 uses.  The parameters are either
  numeric opcode names (usually in octal base), or reference to a symbol, with
  up to 4 parameters (e.g. ``INS86 62, 344`` for ``XOR AH, AH``).  The parser will
  convert the instruction bytes to actual 8086 mnemonics so the next pass in
  the pipeline can more easily convert them to Z80 instructions.

  The ``rasm2`` tool from the `radare <https://rada.re/n/>`_ project was really
  useful in decoding these instructions.  For instance, calling it with ``rasm2 -d  -a x86 -b 16 d3ea``
  in the command line will provide the decoded instruction, ``shr dx, cl``.  Padding
  the instructions with ``00`` (or any other value) will help in cases where ``INS86``
  was called with half a instruction and directives such as ``DB`` (define byte) were
  used right after it.  The conversion tool will print out the code in hexadecimal when
  the arguments are unknown in the same way that ``rasm2`` expects for this reason.

- The ``MOVRI`` macro is used to initialize the ``CX`` and ``DX`` registers. It's
  not clear why it's necessary (and why they couldn't just use ``MOV CX, ...`` instead),
  but I'm going to assume that it's a remnant of previous efforts to port the code
  from the original 8080 assembly into other ISAs, before the automated tool existed.

It also performs some tasks, such as removing macros that are known to not
be used anywhere in the code (and which used instructions that were not
supported by the converter), parses instruction arguments (so numbers are
numbers, in the correct base, etc.), and a few other similar tasks.

Most other tokens are forwarded unmodified to the next step.

Transformer
-----------

This step does some pattern matching and tries to convert some series of
8086 instructions into a series of either Z80 instructions, or some
high-level instruction that the last step is able to generate as Z80
instructions.

In order to preserve the source code comments (which are the most important
thing in this particular historical artifact), each token from the parser is
annotated by the transformer to include a monotonically-increasing numerical
identifier.

The pattern matching works by looking at the instruction stream with windows
of increasing size, and ignoring tokens that aren't instructions or labels:

.. code:: python

    tokens = list(token for token in tokens if token['type'] in {'label', 'instruction'})

    # ...

    for window in windowed(tokens, 2):
        # ...
        matched = self._match(window, ({'JZ', 'JAE', 'JB', 'JS', 'JNZ', 'JNAE', 'JNB', 'JNS'}, (('SHORT', '$+3'),)), ('RET', ()))
        if matched:
            fill_dict(matched, {'op': 'ret_' + self.inverted_jumps[matched[0]['op']], 'operands': ()})
            continue
        # ...

The ``_match()`` function takes a window (as calculated by the ``itertools.windowed()``
function), and a matching pattern to look at. If the window matches the pattern, it
returns the window; otherwise, it returns None so the next call to ``_match()`` can have
a try at looking at that window.

The matching pattern accepted by the ``_match()`` function is quite powerful.  It's a
N-tuple (one element for each element in the window it's supposed to match against),
containing a pair of instruction and tuple-of-operands).  Instructions or operands
can be defined as:

- String: will match that exactly. For example, ``('DEC', ('CH',))`` will match ``DEC CH`` exactly
- Set: any of those will be matched. For example, ``({'DEC', 'DECB'}, ('CH',)`` will match either ``DEC`` or ``DECB``, with the ``CH`` argument
- None: Anything will be matched. For example, ``('JMP', ('SHORT', None))`` will match a short jump to any target

If none of the token IDs are in the transformation dictionary, the
``fill_dict()`` function will first mark all tokens to be deleted from the
stream; then, iterate over its arguments and store the updated token
information.  (The step to mark tokens to be removed from the stream is
necessary for transformations that are shorter than the window size.)

With the transformation dictionary, the transformer step can just go through
it and, if the token ID is in the dictionary, it can either delete it (but
emit a "comment" token if that token had one in the first place), or mutate
the current token before emitting it to the next step.

It took a lot of trial, error, and looking through the whole code and the
Z80 instruction set, to find patterns and things that could be improved in
the "backwards translation" of the GW-BASIC source code.  This thing ended
up being slightly complex, but complex enough to match and transform all
patterns that I could find that required transformation of more than a
single instruction at a time.  As I learned more about the Z80 capabilities,
such as conditional ``CALL`` or ``RET`` instructions, some patterns began to
emerge and this step got some much needed refinement.

Writer
------

The last step is generating the Z80 code.

The first thing that I had to do was figure out the register mapping of 8086
and Z80.  This wasn't that difficult, because a lot of the older code in
GW-BASIC still had comments referencing the Intel 8080 registers, which are
named the same in the Z80.  Some newer code couldn't be mapped to the Intel
8080, but luckily, they could in the Z80 due to the existence of the
indexing registers ``IX`` and ``IY``.

The following table summarizes the register mapping that my converter is
using, based on reading the source comments and the availability of Z80
instructions:

====== ======
8086   Z80
====== ======
BX     HL
BH     H
BL     L
------ ------
DX     DE
DH     D
DL     E
------ ------
CX     BC
CH     B
CL     C 
------ ------
SI     IY
DI     IX
------ ------
SP     SP
AL     A
====== ======

Before writing the Transformation step, I had no clue what I would have to
do with the usage of the `AH` register.  There were some uses throughout the
code base, and there's no equivalent in the Z80: the low part of the 16-bit
register ``AF``, ``F``, is used for flags; it's not really a general-purpose
register.  Luckily, due to the nature of the 8086 GW-BASIC code, uses of the
AH register followed a pattern (emitted by the proprietary Microsoft ISA
converter) that I was able to figure out and emit instructions such as ``EX
AF, AF'``, or ``PUSH AF`` and ``POP AF`` depending on the case.

This last step will either fail assertions when trying to generate an instruction
with the wrong number of arguments, or raise an exception if none of the other
invariants hold.

For instance, the code to generate the Z80 equivalent of the 8086 ``ROR``
(rotate right) instruction is the following:

.. code:: python

    def _gen_instruction_ror(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op2 == 1:
            if op1 == 'AL':
                return 'RRA'
            if not self._is_16bit_reg(op1) and op1 in self.regmap:
                return 'RR %s' % self.regmap[op]
            if op1 == '[BX]':
                return 'RR (HL)'  
        raise SyntaxError("Don't know how to generate ROR with op %s, %s" % (op1, op2))

It'll only recognize uses of the ``ROR`` instruction that makes sense for the
GW-BASIC source code.  This theme repeats over and over again.

Sites such as `MAP <http://map.grauw.nl/resources/z80instr.php>`_, `Z80
Heaven <http://z80-heaven.wikidot.com/>`_, and `this table detailing how
each set of flags are used by each conditional jump instruction
<http://marin.jb.free.fr/jumps/>`_, were immensely helpful.  A few other
sites, such as the `CPC Tech <http://cpctech.cpc-live.com/docs/mult.html>`_
page, or `WikiTI
<https://wikiti.brandonw.net/index.php?title=Calculator_Documentation>`_ had
some wonderful tips that helped me map the 8086 instructions to Z80, and gave
me a few ideas on how to implement instructions such as ``IMUL`` or ``IDIV``.

I also happen to have some deadtree books at home, including the original
Intel manual for the 8086 and a book for Z80 programming targeting the MSX
(although it doesn't really mention the non-documented instructions, of
which some were useful in writing this converter), which were less helpful.
Lack of ``Ctrl+F`` isn't helpful for this kind of documentation.

Last, but certainly not least, I'd like to thank in no particular order,
people like Ricardo Bittencourt, Daniel Caetano, Giovanni Nunes, and Piter
Punk for the help when I was tweeting about this.

Current State and Closing Notes
===============================

The converter tool can do a lot of work already, but it's not complete.  I did
pause the work on it for a while due to personal reasons, but as I mentioned before,
it's being refactored to have an intermediate step between the Transformer and Writer
steps, which should reduce some of the churn when addressing bugs due to invalid Z80
instructions being generated.

Some work has been also being made in other forks of the GW-BASIC source code, where
people are trying to build it using either older versions of the Microsoft Assembler
and Linker, or using more modern tooling such as JWAsm and JWLink.  Some of the code
to make the interpreter work is missing, but it's mostly platform-specific glue code,
which is being either reimplemented from the scratch, or reverse-engineered from the
`BASICA.COM` code that was released previously under the MIT license.

Some of the missing symbols had names that were suspicious to me, and, indeed, many of
them were actually names of BIOS functions from the MSX.  Considering that Microsoft
designed the BIOS in those computers, it's not really surprising.  (It's good, too,
because I wouldn't need to reimplement those things if I ever get this to work on the
MSX.)

My idea, eventually, is to use this as a base for a BASIC interpreter in the
C-BIOS project, which is an open source BIOS for the MSX computers.  It
currently lacks the BASIC component, and using one that's essentially the
same that shipped with the MSX would be a good starting step.  Of course, a
lot of the hardware-specific things, such as the ``PLAY`` command (which has
3 channels in the MSX, and is extensible to use FM synthethizers and
whatnot), general extensibility via hooks in ROMs attached to the computer,
and many other MSX-specific routines will need to be implemented.  I'm not
really worried about all this, however, as I'll be really happy if I could
fill the screen with the quintessential BASIC Hello, World:

.. code:: plain

    10 ? "Hello, world! ";
    20 GOTO 10

This work is open source and I `appreciate help if this is the kind of rabbit
hole you'd like to burrow in <https://github.com/lpereira/gw-basic>`_.
