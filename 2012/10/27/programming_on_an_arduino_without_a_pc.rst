Programming on an Arduino without a PC
======================================

I’ve attended this year’s `FISL`_, both as a booth attendee (at
`ProFUSION`_’s booth, demonstrating a few of our end-user-visible projects),
and as a speaker for my old `FINF`_ project.

FINF is a `Forth`_-like programming environment that I’ve written in my first
year at the college. It’s not the first compiler I wrote, but it was the
first that was actually fun to write. Some years later, I’ve decided to
rewrite it so that it would work on the `Arduino`_ – and that’s what I went
to FISL to talk about.

.. image:: http://i.imgur.com/AsCOr.jpg
    :alt: audience


Arduinos are traditionally programmed by using its IDE, in a language that
resembles C++. In fact, it is C++, but some of the (boring) details are
hidden. But, being C++, it’s bound to the slow write-compile-upload-test
procedures; there’s no interactive prompt, such as you have with Python or
the venerable 8-bit Microsoft Basic. And since Arduino is all about
experimentation, an interactive prompt is a must.

FINF is there to fill this gap. It is not a full `FORTH`_ implementation;
only a small subset of it is there, but it’s enough to blink some LEDs, make
some noise, and – if a video output shield is used – use the Arduino as an
8-bit computer! But, since user code actually runs on top of a very simple
virtual machine due to the `Harvard architecture`_ used by the AVR
microcontroller, it’s not possible to expand the interpreter without getting
dirt in your hands. Add that to the quite messy code, mix it with myself not
being a good marketer, and you have yet another failed open source project of
mine! :)

In any case, the `slides`_ (in Portuguese) are available online.
Unfortunately, the presentation was not recorded, so if you were not there,
you’ve missed the great opportunity of seeing myself making a LED blink in
front of an audience.

(By the way, I’ll be talking during EFL Developer Day in Barcelona early next
month. If you’re there for LinuxCon/Embedded Linux Conference and would like
to join me for some beers, don’t hesitate to contact me!)

.. _FISL: http://softwarelivre.org/fisl13
.. _ProFUSION: http://profusion.mobi
.. _FINF: http://github.com/lpereira/finf
.. _Forth: http://en.wikipedia.org/wiki/Forth_(programming_language)
.. _Arduino: http://www.arduino.cc
.. _Harvard architecture:
    http://en.wikipedia.org/wiki/Harvard_architecture
.. _slides: https://docs.google.com/presentation/d/1w23aLeFgbvjztjtDIFcGT
    Al7ghlfxsxH_lW4Fyw8lzw/edit



.. author:: default
.. categories:: none
.. tags:: profusion,finf,conferences,arduino
.. comments::