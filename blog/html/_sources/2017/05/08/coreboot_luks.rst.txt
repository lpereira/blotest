Coreboot & LUKS
===============

My laptop is a 6-year old `ThinkPad X220
<http://www.thinkwiki.org/wiki/Category:X220>`_.  Although it's almost
falling apart from years of constant abuse, I don't see myself replacing it
anytime soon: it's easy to repair, has a great keyboard, and is a very
dependable machine.

And it's supported by `Coreboot <https://en.wikipedia.org/wiki/Coreboot>`_. 
Substituting the proprietary firmware with it is very trivial: I followed
the instructions on `this blog post
<https://tylercipriani.com/blog/2016/11/13/coreboot-on-the-thinkpad-x220-with-a-raspberry-pi/>`_
and they worked out of the box.  (I also went the extra mile and flashed the
firmware after passing it through `me_cleaner
<https://github.com/corna/me_cleaner>`_.)

.. figure:: https://i.imgur.com/97rTiZH.jpg
    :alt: flashing X220 bios
    :align: center

    Flashing the serial flash using a Raspberry Pi 3. Yes, I need to clean
    up this computer.

The major difference from my previous setup is that my SSD had
`hardware-based full disk encryption
<https://en.wikipedia.org/wiki/Hardware-based_full_disk_encryption>`_.  I
ended up disabling this for two reasons: first, this isn't very secure (the
key will remain in the disk RAM for as long as power is supplied); second, I
was not sure if Coreboot supported this.  So I disabled encryption prior to
flashing the new firmware.

But keeping a hard drive unencrypted on a laptop isn't good practice.  I
decided to use `LUKS <https://en.wikipedia.org/wiki/Linux_Unified_Key_Setup>`_
instead.

However, instead of using `SeaBIOS <https://en.wikipedia.org/wiki/SeaBIOS>`_
as the payload and have a standard bootloader, I opted to go through a
slightly different route: have a custom-built Linux inside the ROM, open the
``/boot`` partition with LUKS, and
`kexec <http://man7.org/linux/man-pages/man2/kexec_load.2.html>`_ the current
vmlinuz/initrd.

Compared to the usual setup of using SeaBIOS as a payload, this setup
reduces boot time by cutting the middlemen.  With the ability to boot from
external devices removed, it's also arguably more secure.  The in-ROM Linux
has only the bare minimum: no network subsystem, only necessary filesystems,
bare minimum drivers are built-in, USB is limited to HID devices, etc; the
compressed kernel has ~1.7MiB with room to shrink.  The in-ROM initrd is
also quite minimal, containing just one file.

The only file is a `hacked version
<https://gist.github.com/lpereira/845fe060ba68a5db95827cbc5496bb6d>`_ of
cryptsetup that acts as a primitive init, creating ``/proc``, ``/dev`` (and mounting
these two), and ``/boot``, decrypting ``/boot``, and performing kexec.  It's
statically linked with `musl libc <https://www.musl-libc.org/>`_.

Flashing this requires opening the laptop, and I'm planning to do this next
weekend when replacing the USB ports.  However, the setup works very well
under `QEMU <http://www.qemu.org/>`_.

This blog post isn't meant as a tutorial -- feel free to contact me if you
have questions or ideas on how to improve this.  If you end up using
something similar to this idea, I'd love to know as well.

.. author:: default
.. categories:: linux, x220, hack
.. tags:: none
.. comments::
