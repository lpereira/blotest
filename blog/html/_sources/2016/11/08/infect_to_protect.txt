Infect to Protect
=================

Bandwagons
----------

I’m not one to jump on each and every bandwagon I see. Sometimes that’s a
good decision, sometimes it’s better to just wait and see where they go
before taking any action.

Containers are one of those ideas that, while promising and intriguing, were
quite clumsy in the beginning, so I ignored them for a good while.  It’s
sufficiently mature now; so much so that’s quite difficult to ignore them. 
Time to investigate them again.

Now, most of my work revolve around writing embedded software that runs on
bare metal; containers don’t really solve any work-related problem I have. 
For personal usage, package management is more than sufficient to install
programs.  However, the sandbox aspect of containers are quite interesting
and it’s something I’d like to know more about.

There are many articles around the web explaining how containers on Linux
work.  Some get out of their way to explain depth all the machinery
necessary to make them work, so there’s no need to repeat it here.

But, in sum: almost all of the `kernel side of things was already present
<http://jvns.ca/blog/2016/10/10/what-even-is-a-container/>`__ before
containers were actually a thing: cgroups, system call filters, etc. 
Containers (and their runtimes) only make them so simple to use it’s
transparent for the user.

I usually have a hard time understanding things that I cannot build, so I
decided to build a toy container runtime.  It’s crude and it’s a far cry
from what any industrial-strength container runtime is capable of, but it’s
not only a start, it’s implemented in a way that makes things a
*lot* easier for the user.

Virulent tutorials
------------------

Before I go into details on how my contraption works, a little bit of
background. I’ve been using Linux for over 18 years, and began my forays
in C about 14 years ago.

Around that time, a pretty interesting HOWTO explaining `how to create
viruses for ELF binaries
<http://virus.enemy.org/virus-writing-HOWTO/_html/>`__ came out.  It
explained not only various methods of infecting an ELF executable, but also
methods to detect them.  Suffice to say, I couldn’t understand a thing back
then.  A few months ago, though, a conversation in the `local hackerspace
<https://lhc.net.br>`__ brought up that tutorial; I could now finally
not only understand the techniques but put them to use.

One of the techniques explained in the HOWTO involves finding some
unused space in an ELF segment that’s also executable, writing shellcode
to that area, rewiring the executable’s entry point to point to the shell
code, and modifying the shell code so that it points to the original entry
point. It’s all quite Rube Goldberg-ey, but it’s actually quite simple.

This way, a chunk of code can be executed every time that program
starts, without altering the size of the program. The perfect crime.

.. figure:: https://media.giphy.com/media/oX13doUEAPtIY/giphy.gif
    :alt: Perfect crime
    :align: center
    :width: 50%

Dual use technology
-------------------

By now, you’ve most likely connected the dots: the idea is to use the
very same technique, originally designed for viruses, to create a program that
transforms any program into a sandboxed version of itself.

The prototype I wrote is very elementary; the only thing it does is
limiting, just once, which system calls a program can execute.

Sort of a less-powerful version of `OpenBSD’s
pledge(2) <http://man.openbsd.org/cgi-bin/man.cgi/OpenBSD-current/man2/pledge.2>`__
(née ``tame(2)``), which can be repeatedly called to reduce the amount of
privileges a process has. Useful, for instance, in cases where a
configuration file has to be read before processing user-supplied work.
That BSD version has `been sprinkling calls to
pledge() <https://www.openbsd.org/papers/hackfest2015-pledge/mgp00001.html>`__
in almost all of the programs in the base install (which is easier for a
BSD system, since everything is kept under the same roof.)

But, unlike ``pledge(2)``, this thing can be applied to binaries that have
been already built. No source code modifications are necessary. If your
distribution can withstand the stench, "infected" binaries could be a
thing in the default installation.

Filtering the system calls
--------------------------

Any respectable container runtime will perform a lot of tasks to sandbox
a process and their children. So, for a proof of concept, I decided to
do just the bare minimum: limit system calls using Seccomp-BPF.

`Seccomp <https://en.wikipedia.org/wiki/Seccomp>`__ is a set of features
present in the Linux kernel, since the 2.6.x days, that allows
restricting what a program can do, system call-wise. The original intent
was to do not permit any other system calls excepting those to end the
program, and read and write to already-opened file descriptors. In some
scenarios, this is perfectly acceptable. For others, there’s the
seccomp-BPF extension.

BPF stands for `Berkeley Packet
Filter <https://en.wikipedia.org/wiki/Berkeley_Packet_Filter>`__. A
famous use of BPFs is in the tcpdump program, where rules such as "only
give me back TCP connections with the RST flag set" can be passed to the
kernel; packets that don’t match the filter are not copied back to the
userland, reducing a lot of the chatter between the two lands.

Obviously, this must be extremely performant, since kernel time must be
conserved at all costs (the kernel is there only to serve userland,
after all). Linux has many ways to speed up BPF programs, including an
in-kernel JIT. Some restrictions are in place that wouldn’t allow BPF
programs to take an infinite amount of time to execute, and this `blog
post <https://blog.cloudflare.com/bpf-the-forgotten-bytecode/>`__ is a
good introductory reading material on the subject.

Another, slightly less famous use of BPFs is with the seccomp-BPF
extension. Instead of filtering network packets, processes can, for
instance, pick which system calls they’re allowed to perform. And that’s
precisely what’s necessary for my proof of concept.

Scripting like a kid
--------------------

There are many ways to skin a cat. I decided to take a look how other
programs were doing their sandboxes, and eventually `found one that
seemed easy
enough <https://github.com/brynet/file/commit/612a76f47d879d8c7cc5791b49a3704b54391e05>`__
to copy the technique from.

Unfortunately, writing shellcodes in C isn’t that easy, specially if you
don’t know which C library a program was linked with (or if it were
linked to a C library in the first place). Luckily, all the shellcode
has to do is make two system calls, which is straightforward to do with
a little bit of assembly.

The first call will forbid the process from getting more privileges. The
second call will actually copy the BPF program to the kernel side.

The first call is painless: just set a few registers, invoke the syscall,
done.

The other one takes a little bit more work. A few things helped: I’ve
used `nasm <http://www.nasm.us/>`__, which is a `macro
assembler <https://en.wikipedia.org/wiki/Assembly_language#Macros>`__,
and wrote a few macros that let me write BPF programs as if they were
standard x86-64 instructions.

The remaining issue is that a pointer to the BPF program must be passed
to the call to ``prctl()``, and the shellcode must be relocatable. A `common
trick <http://stackoverflow.com/a/15704848>`__ to perform in these
scenarios is to employ the fact that, on x86, when a call instruction is
made, the return address (i.e. the address of the byte right after the
call instruction) is pushed to the stack:

.. code-block:: nasm

    	; …
    	jmp push_bpf_addr
    apply_filter:
        pop rdx     ; rdx points to the BPF program
        ; …
    push_bpf_adr:
        call apply_filter
    bpf:
        bpf_stmt ; …
        bpf_jump ; …
        sc_allow ; …
        ; …
    bpf_end:

The ``bpf`` label doesn't point to any x86 instruction: it contains only
macros that expands to the definitions of ``struct sock_filter`` as defined
in ``linux/filter.h``.  To copy the BPF program to the kernel, the `prctl()`
call expects a ``struct sock_fprog``, which contains the BPF program length
(in number of ``struct sock_filter`` elements), and a pointer to the base of
that array.  Since there's no way to know where this code is gong to land in
memory beforehand, this trick comes in handy: after the ``call
apply_filter`` instruction, the top of the stack now contains the base
address that array.

Now that I had a way to write the shellcode, it was just the matter of
shoehorning it into the executable.

.. figure:: https://media.giphy.com/media/l46C6sdSa5DVSJnLG/giphy.gif
   :alt: Hacking time
   :align: center

Scoring a goal
--------------

For the proof of concept, I was initially going to write the infection
program in Python, as I usually do for throwaway code.  However, I wasn't
successful in finding a working ELF library that would let me dump the
modified executable.

I was too lazy to actually fix or write support for that, so I kept
looking for alternatives and ended up finding the
`ELFkickers <http://www.muppetlabs.com/~breadbox/software/elfkickers.html>`__
suite from the always excellent Muppet Labs. It includes an "infect"
program that does exactly what says in the tin: it takes in an
executable file, and produces another executable file that creates a
setuid shell before continuing to the original program. Exactly what one
would expect from a program with nefarious purposes.

So I substituted the original shellcode for the one I’ve just assembled, and
now I had a proof of concept.  Which of course didn’t work the first few
tries.  In fact, it took a long while to get it right.

Debugging the contraption with gdb
----------------------------------

The GNU Debugger is indeed very powerful, but ease of use (compared to
the Turbo Debugger I used to use in the DOS days) is not it’s strong
suit. I’m not used to using it to debug programs without access to
source, and this was a good opportunity to learn a few things.

Since the infection program modifies the ELF entry point, setting a
breakpoint on ``main()`` won’t actually work. But this is easily solvable:
just use `readelf(1) <https://linux.die.net/man/1/readelf>`__ to find
where the new entry point is, and set a breakpoint to that:

.. code-block:: shell-session

    $ gcc -o hello hello.c
    $ readelf -h hello | grep Entry
      Entry point address: 0x400490
    $ ./infect hello
    $ readelf -h hello | grep Entry
      Entry point address: 0x4007bc
    $ gdb ./hello
    …
    (gdb) break *0x4007bc
    Breakpoint 1 at 0x4007bc

From now on, it’s just the usual
execute-inspect-modify-reassemble-reinfect loop until it works. Although
it’s no `td <https://www.youtube.com/watch?v=-ueCuJXF6po>`__, I’m
certainly glad GDB has layouts that displays both the `disassembly and
the
registers <https://reverseengineering.stackexchange.com/questions/1935/how-to-handle-stripped-binaries-with-gdb-no-source-no-symbols-and-gdb-only-sho>`__.

.. figure:: http://data.photofunky.net/output/image/f/b/5/0/fb50ca/photofunky.gif
   :alt: Step-by-step debugging
   :align: center
   :width: 50%

Watching the magic happen
-------------------------

The ``hello`` program is very short and the call to ``socket(2)`` doesn’t
make much sense there.  It’s just a way to test what’s going to happen when
the filter is in place, without the need to modify the program to test this
assumption.  (`Lots of things
<https://www.bsdcan.org/2016/schedule/attachments/357_20160610-bsdcan-helloworld.pdf>`__
happens when executing a simple program such as this.)

.. code-block:: c

    #include <stdio.h>
    #include <sys/socket.h>
    #include <netinet/in.h>

    int main(int argc, char *argv[])
    {
	if (argc < 2) {
		printf("no socket created\n");
	} else {
		int fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
		printf("created socket, fd=%d\n", fd);
	}
	return 0;
    }

Executing the program before infecting it gives the following output, as
expected:

::

	$ ./hello
	no socket created
	$ ./hello 1
	created socket, fd = 3

Indeed, if the program is executed under strace, it all goes exactly
like it’s supposed to be:

::

	$ strace ./hello
	execve("./hello", ["./hello"], [/* 58 vars */]) = 0
	…
	write(1, "no socket created\n", 18no socket created
	)     = 18
	exit_group(0)                           = ?
	+++ exited with 0 +++

And, with a command-line argument, so the socket is created:

::

	…
	socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 3
	…
	write(1, "created socket, fd = 3\n", 23created socket, fd = 3
	) = 23
	exit_group(0)                           = ?
	+++ exited with 0 +++

However, the magic happens after the "infected" binary is executed.
First, without creating a socket:

::

	…
	prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)  = 0
	prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, {len=30, filter=0x400824}) = 0
	…
	write(1, "no socket created\n", 18no socket created
	)     = 18
	exit_group(0)                           = ?
	+++ exited with 0 +++

Notice the calls to ``prctl()``, very similar to the ones found in the
previously-mentioned commit. And then the program executes as usual.
Now, if an argument is passed, the program will attempt to create a
socket:

::

	…
	prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)  = 0
	prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, {len=30, filter=0x400824}) = 0
	socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 41
	--- SIGSYS {si_signo=SIGSYS, si_code=SYS_SECCOMP, si_call_addr=0x7f2d01aa19e7, si_syscall=__NR_socket, si_arch=AUDIT_ARCH_X86_64} ---
	+++ killed by SIGSYS (core dumped) +++
	[1]    27536 invalid system call (core dumped)  strace ./hello 1

And Seccomp kicks in and kills the program with a ``SIGSYS`` signal. As
expected. **It's alive!**

.. figure:: https://i.imgur.com/sWwquxp.jpg
   :alt: It's alive!
   :align: center

Next steps
----------

The prototype works. But there are a few things that must be considered
before even considering this idea for anything.

System call whitelist
~~~~~~~~~~~~~~~~~~~~~

The list of system calls is still hardcoded within the shellcode. That’s
not optimal. Maintaining a list such as this for each and every program
will most likely be so boring nobody is going to do that.

I can think of three possible ways of coming up with this list.

The first would be doing the same thing ``pledge(2)`` does: allowing a very
restrict set of system calls at first, with some limitations, and then
providing a few sets of calls per set of features a program might use: stdio,
inet, tty, etc.  The nice thing about this is that the filters are more fine
grained; it’s not just a whitelist of system calls.  (The `man page
<http://man.openbsd.org/cgi-bin/man.cgi/OpenBSD-current/man2/pledge.2>`__ has
more details.)

The second way would involve running the program under ``strace(1)`` and
record which system calls the program makes from a few runs.  If the test
coverage for each run is sufficiently high, this will work very reliably;
this isn't always the case, so the mileage may vary.  Also, for certain
large, complicated programs, stracing it all automatically could prove to be
a challenge.

Another way would be the following: Grab a list of undefined symbols a
program uses, and find them in the shared libraries it links to.  Then scan
the executable and the libraries for sequences like ``mov eax, 57; syscall``
(for the oldschool ``fork(2)`` syscall on x86-64) or ``mov eax, 57; call
syscall@plt``.  This is still not foolproof, since not necessarily a system
call number (loaded into ``eax``) will be hardcoded within a program or
shared library.

There’s a fourth idea, as well, which involves both doing the automated
static analysis on the binary and running strace to catch "runaway"
syscalls. This can get quite complicated and it’s unlikely I’ll get it
correct in the first few tries (and, yet, the same shortcomings will
apply in the end.)

For me, though, these experiments are all about the hunt, not about the
treasure. So the tried and true approach that ``pledge(2)`` uses won’t be
used at first.

Filter optimization
~~~~~~~~~~~~~~~~~~~

Another thing that might be a problem is: on x86-64, Linux has hundreds of
system calls.  (329 according to ``sys/syscall.h`` at the moment I write
this.)

Even if the JIT for BPFs is quite efficient, doing a linear search before each
an every system call will certainly be a bottleneck.  Also, BPF programs are
limited in size, and a large whitelist that’s implemented the same way as the
prototype will limit the possibility for more fine-grained filters.  Things
like "the ``socket(2)`` call is allowed only for UNIX-domain sockets", rather than
allowing whatever call to ``socket(2)`` would be impractical.

Since each syscall is identified by a number, a simple bitmap could be
used to implement the whitelist. This will also free up some space in
the BPF program for more detailed whitelisting for certain syscalls (for
instance, only allowing certain family of sockets to be created).

After a quick read of
`networking/filter.txt <https://www.kernel.org/doc/Documentation/networking/filter.txt>`__,
this seems doable by using an algorithm such as this, which will reduce
the number of comparisons as the number of acceptable system calls
increases:

::

                if syscall_number < 32:
	                if bitmask_0 & 1<<syscall_number: goto accept
                if syscall_number < 64:
        	        syscall_number -= 32	
                	if bitmask_1 & 1<<syscall_number: goto accept
                if syscall_number < 96:
                        syscall_number -= 64
                        if bitmask_2 & 1<<syscall_number: goto accept
                …
                if syscall_number < 352:
                	syscall_number -= 320
                	if bitmask_10 & 1<<syscall_number: goto accept
                return SECCOMP_RET_KILL
	accept:
		return SECCOMP_RET_ACCEPT

(Some of the ``if syscall_number < N`` blocks could be changed to
``syscall_number -= M`` if their respective bitmask is ``0``.)

Or maybe just a bloom filter instead of a series of bitmaps. I’ll have
to experiment.

Getting a larger vessel
~~~~~~~~~~~~~~~~~~~~~~~

Containers, of course, are not just about restricting which system calls a
program is allowed to perform.  There are many things that can and must be
considered before even calling this a container runtime, or really consider
that this is in fact sandboxing anything.  Learning about namespaces,
cgroups and virtual machines are certainly on the list of things to learn
about.

Conclusion
----------

While the prototype I built isn’t practical and is of very limited use,
I find the idea of sandboxed programs without the need for specialized
runtimes very enticing.

Programs can be still packaged the way they have been packaged in the
past decades, without throwing away some of the sandboxing benefits that
containers provide, all the while not introducing new concepts for
users.

Of course, something like this -- even if properly implemented -- won’t
be a replacement for containers. Specially if one considers their role
as packets ready for deployment, which have a lot of value for devops
personnel.

The code, as usual, is open source, and available from `this Git
repository <https://github.com/lpereira/infect-to-protect>`_.

.. author:: default
.. categories:: none
.. tags:: container, assembly, linux, bpf
.. comments::
