Reducing Lwan memory usage by 2670%
===================================

One of the things that bothers me when I'm writing software is that I `never
get things right the first time`_.  It takes me quite a few iterations to
achieve a good result -- be it performance, memory usage, or a good
architecture.  Getting things to a "good enough" state is also very frequent
as projects need to move forward; however, written code often ends up in
sort of a low priority refactoring thread inside my head.  Sometimes this
thread is able to produce a thing or two, and I'm able to revisit these
things.

.. figure:: http://farm1.staticflickr.com/64/169229347_f554a9c9ea.jpg
    :alt: projectmovingforward
    :align: center

    Project moving forward picture by `Todd Smith`_. Sometimes you're so
    focused on the goal that you end up not appreciating the journey.

Background toys
---------------

One of the things that were in that refactoring thread was `my toy web
server`_'s memory usage.  It would consume a whopping **855MB** of memory
while idling; recent commits dropped this amount to a mere **32MB** (with
maybe some more room to spare).  That's around **2670%** less memory.

This was only possible because I know the code inside out and was able to
refactor the code a few times.

.. figure:: http://i.imgur.com/xSB5PZp.png
    :alt: massifscreenshot0
    :align: center
    :width: 100%

    Massif-visualizer windows shown at different scales.

Structure diet
--------------

Lwan allocates almost all memory it is going to need even before creating
the main socket.  This means it has to keep around some structures with
information about connections, requests, and their responses.

The first drop in memory usage was the highest one. It was possible because
the structure that keep state for these things also kept state that was only
useful during the request parsing stage.  By segregating this temporary
state to another structure, which is allocated in the request parsing
routine stack, memory usage fell dramatically.

Lots of flags were saved using bitfields in different substructures. Most of
these were booleans, and having less than 32 of them meant I could coalesce
all of them in a single unsigned integer.  Memory usage dropped again.

Architecture smell
------------------

Then a few months passed, and out of the blue I realized that there was
something wrong in the architecture: the same structure I was using to track
request state, I was also using to track connection state.

So I moved all things that only matters to a connection to a structure --
which is the structure that's preallocated on startup -- and made the
request structure be allocated in the request processor routine's stack. 
This stack lives in a coroutine -- which won't use more memory than it was
already allocated for the coroutine stack.  Another worthy reduction of
memory usage.

This also made keep-alive connections a tiny bit faster, as there's no need to
``memset()`` the request structure to clean state for the next request
anymore.

.. figure:: http://i.imgur.com/3BrC0KB.png
    :alt: massifscreenshot
    :align: center
    :width: 100%

    Same scale this time. *That drop*.

Reducing it further
-------------------

There's another possibility for memory reduction, but I'm not sure if it is
worthy implementing.

Lwan uses ``epoll()`` -- and when a file descriptor is added to a poller,
one can pass arbitrary data inside ``epoll_data_t``, up to 64-bit in size. 
Both the file descriptor and the remote IP address could then be passed as
this data, removing both fields from the connection structure.

This is possible because these are constant values while the connection is
active; everything else is either useless to identify the connection (the
file descriptor is used as an index in an array of connections) or changes
all the time, such as the flags (which would incur the penalty of calling
``epoll_ctl()`` every time they change).

This would reduce structures by a few megabytes, which isn't really worth
the effort considering IPv6 support would need to be implemented someday and
this trick would be then rendered useless.  Maybe my refactoring thread will
be able to answer that in a few months.

I'm still considering if it is worthy the trouble of leaking the
request/connection abstraction and removing an integer from the request
structure so all request-related flags would be set in the connection
structure.

.. author:: default
.. categories:: none
.. tags:: lwan,programming
.. comments::

.. _my toy web server: http://github.com/lpereira/lwan
.. _never get things right the first time: https://www.youtube.com/watch?v=csyL9EC0S0c
.. _Todd Smith: http://www.flickr.com/photos/tsdesign/
