Projects
========

This is a curated list of personal programming-related projects I've worked
on in my spare time.  (Some of these projects are still being maintained.)

Lwan
----

.. image:: https://lwan.ws/lwan.svg
   :align: right
   :width: 128px

I usually write web servers when learning a new programming language, as a
project.  This gives me a really good feel about a language, especially for
the things I usually care about, such as concurrency, string processing,
networking, and I/O.  Lwan, a high-performance web server, however, started
as a "what if" kind of project; I was already experienced in the C programming
language when I decided to write it, and over the years I've spent countless
hours poking around and improving it.

A lot of the things I write in this blog is related to this project, which ended
up being an umbrella project for experimentation.

More information can be obtained from its `web site <https://lwan.ws>`__.

HardInfo
--------

System profiler and benchmark software for Linux.  Back when I was a PC enthusiast,
I loved this kind of program on MS-DOS and Windows systems; I could never resist
installing them and going through all the information they could gather.  When I
started using Linux, I had this itch that I would only scratch a few years later.

HardInfo is one of my oldest open source projects still being maintained.  The `first
version was released in 2003 <http://freshmeat.sourceforge.net/projects/hardinfo>`__.

.. figure:: https://tia.mat.br/temp/img/hardinfo-parport.png
    :align: center

    One of the first few versions of HardInfo, showing a Parallel Port device. Yes, I had a Parallel Port webcam back in the day.

It used to be available in pretty much every Linux distro in their official repository,
but due to my lack of interest over the years, and lack of updates, not many distros
carry it anymore.  There has been some recent interest after some people decided to
fix some bugs and implemented much-needed features, so we're slowly working towards a
new release after 10 years without one.

.. figure:: https://tia.mat.br/temp/img/hardinfo-ptbr.png
    :align: center

    The last UI before the current rewrite.  I actually quite like this one.

The project still tries to obtain information using methods that were necessary in the
days of Linux 2.0 or 2.2.  The code is really hard to maintain, due to a few bad
decisions, and it deserves a rewrite; maybe someday.

.. figure:: https://tia.mat.br/temp/img/hardinfo0.4.png
    :align: center

    Version 0.4, the first UI to sport the current UI.

SuxPanel
--------

Clone of the GNOME 2.0 panel, written when I had a computer with limited resources
but still wanted the same experience.  It could be extended by plugins that were
loaded with ``dlopen()``, and came with quite a few of them, including launchers,
mixers, mail monitor, and other useful things.  It was even featured in Linux
Magazine.

The `repository is archived in my GitHub <https://github.com/lpereira/suxpanel>`__.

.. figure:: https://tia.mat.br/temp/img/suxpanel.png
    :align: center

    SuxPanel screenshot from back in the day

GW-BASIC port for the Z80
-------------------------

Microsoft released the source code for the first version of their GW-BASIC
interpreter for MS-DOS under the MIT license.  This version is based off of
the same BASIC that kickstarted the company, and thus contains original
comments from the late 70s.  The first programming language I used was the
MSX-basic, which is supposedly derived from GW-BASIC; the MSX, however, had
a Z80 processor (which is instruction-compatible with the Intel 8080
processor, used in the Altair computer that ran the first MS-BASIC), and the
MS-DOS version was of course written for the 8086.

Many comments reference 8080 registers (which are mostly the same in naming
as the Z80 registers), instead of the actual 8086 registers that the
instructions are operating with.  This is because the source code was
mechanically translated by a tool which hasn't been, unfortunately, released
as open source software.

So, in order to better understand the first language I used to program on
and the machine I used to use (I never had an opportunity to program in Z80
assembly language before), I decided to write a
`tool to convert the 8086 code back to Z80 <https://github.com/lpereira/gw-basic>`__.

A lot of the code can be translated with this tool; however, the code
doesn't yet assemble.

Gomoku
------

Gomoku was a failed attempt at writing a Go-to-C++ converter, so that the
resulting program could be built with GCC/Clang and target embedded devices.
The code isn't that great, as that was my first program written in the Go
programming language, but I had a lot of fun writing it.  I decided to abandon
this project as a better alternative, that uses LLVM directly, is now working
properly and has attracted a healthy community.

For instance, the following Go program from the "Go Programming Language" book:

.. code:: go

    func corner(i, j int) (float64, float64) {
            // Find point (x,y) at corner of cell (i,j).
            x := xyrange * (float64(i)/cells - 0.5)
            y := xyrange * (float64(j)/cells - 0.5)

            // Compute surface height z.
            z := f(x, y)

            // Project (x,y,z) isometrically onto 2-D SVG canvas (sx,sy).
            sx := width/2 + (x-y)*cos30*xyscale
            sy := height/2 + (x+y)*sin30*xyscale - z*zscale
            return sx, sy
    }

Is translated to C++ like so:

.. code:: c++

    std::tuple<double, double> corner(int i, int j) {
      double sx{0};
      double sy{0};
      double x{0};
      double y{0};
      double z{0};
      x = xyrange * (double(i) / cells - 0.5);
      y = xyrange * (double(j) / cells - 0.5);
      z = f(x, y);
      sx = width / 2 + (x - y) * cos30 * xyscale;
      sy = height / 2 + (x + y) * sin30 * xyscale - z * zscale;
      return {sx, sy};
    }

Maybe someday I'll restart the project, but do so in a completely different
way.  There are advantages beyond the original intent with the code, e.g. 
using parts of the Go standard library, which is well-designed, in C++
programs, and leverage the improvement in code generation by more mature
compilers.  For the time being, though, this project is on hold.

Slot Machine
------------

This was my first (and only) game for the MSX computers.  It's terrible take on
Slot Machines, using graphics ripped off of the Klik&Play graphics pack.  It's
written in Turbo Pascal 3, and requires a MSX2 computer.

See the video of it in action, or `play it online <http://webmsx.org/?DISKA=https://tia.mat.br/temp/slotmac.zip>`__
(source code can be found in the ZIP file that the online emulator uses).

.. youtube:: IvT7NQmj7w0

FINF
----

FINF Is Not Forth is a FORTH-like language/environment for the Arduino.  It's not the
best code I've written, but it works and is quite useful to fool around and perform
quick experiments with sensors without having to re-flash the firmware every time.

I `did a presentation about it
</posts/2012/10/27/programming_on_an_arduino_without_a_pc.html>`__ a few
years back.

.. figure:: https://camo.githubusercontent.com/7eb04081607b2f533706386a76527c7f71fc475c/687474703a2f2f692e696d6775722e636f6d2f546f7267562e706e67
    :align: center

    FINF as seen by ``Terminal.app`` in an older MacOS X

Pense-Bem Simulator
-------------------

Pense Bem, sold as Smart Start in the US and Canada, was a toy made in the late 80s
and early 90s under license by Tec Toy in Brazil.  My parents couldn't afford one,
and I always wanted to play with one.  One day, I got together with a friend set out
to reverse engineer one and write an emulator for it; we couldn't dump the ROM (no
knowledge/equipment on how to do that at the time), so we wrote a simulator, doing
a clean-room reimplementation of the whole thing.

It is written in JavaScript, using SVG for the interface.  It can be `played
online <http://labs.hardinfo.org/pb/>`__.

.. figure:: https://tia.mat.br/temp/img/pensebem.png
    :align: center

    Guess the number!  (Or, how to teach binary search to kids.)

AcidIM
------

.. image:: https://tia.mat.br/temp/img/acidim-shot.gif
    :align: right

This was my attempt at writing an instant messenger in the year 2000. 
Inspired by ICQ and written in Perl it even featured WebCam support (by
detecting if the user had `camserv <http://cserv.sourceforge.net/>`__ installed).

Written in an era before XMLHttpRequest, Server-Sent-Events, and WebSockets, this thing
had a borderless frame that reloaded every few seconds to show a different icon if
there was a pending message.  In retrospect, I should have used long-polling mode and
send ``<script>`` tags to control the other frame; this kind of thing was allowed back
then.

ROX Menu
--------

ROX, or RISC-OS on X, was a desktop environment for the X11 system that replicated,
as the name implies, the user experience of the RISC-OS operating system.  It had an
interesting way of storing information about applications, very similar to what MacOS
does (applications are folders), but provided no application launcher in a menu, similar
to Windows' Start menu.  ROX-Menu was exactly this: a panel applet that would show in
a menu a hierarchy of directories and AppDirectories and allow you to launch applications.

.. figure:: https://tia.mat.br/temp/img/rox-menu.png
    :align: center

    Screenshot stolen without shame from the `current maintainer <https://www.skepticats.com/rox/rox-menu.html>`__


Visual Python
-------------

I used to program in Visual Basic 4, and I missed it dearly when I started
using Linux in the late 90s.  When I learned Python, I thought it could be
the language to replace VB for me, but there was no IDE-like experience to
replace it.  So I set out to replicate this.

I thought I had completely lost the source code for this project, but I
found an old version of it in an external hard drive.  After hacking to
remove some features that were stubborn enough to not work on a modern
system, the main UI ran and worked as expected.

.. image:: https://tia.mat.br/temp/img/vbpython.jpg
    :align: center

Unfortunately, basic things like the code and property editor had to be
neutered to take the screenshot below, but the project was taking shape
right before I joined university and had to dedicate my time to Calculus,
Physics, and Chemistry.

This is a project that's definitely in the bucket list for something that
I want to do again.


