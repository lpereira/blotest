Hash trie
=========

`Tries`_ are very useful data structures if you need to perform longest
subprefix matching. Unfortunately, simple implementations uses a lot of
memory, which is often solved by collapsing common prefixes in a single node
(like a `Radix tree`_). However, this adds to the implementation complexity,
which is something I like to avoid.

`Lwan`_’s original trie implementation required 256 pointers per trie node
(one per possible byte). This is not only wasteful, but also meant lwan would
get a lot of cache misses.

Instead of just using a `Radix tree`_, I decided to keep the same basic
implementation but lower the number of pointers per node to just 8 – and hash
each key byte by calculating ``MOD 8``. This was a very cheap optimization,
which works pretty well.

But this optimization leads to the same problem found in `hash tables`_:
`collisions`_. The problem is minimized by the fact that collisions can only
happen when using keys with the same length – which is uncommon in the basic
use case for these tries in `lwan`_: matching URLs by their prefix to
determine which handler to call.

Nonetheless, this is easily fixed by adding a linked list to each leaf node.
To avoid having to perform one last string comparison if there’s just one
node in this linked list (and hence no collisions), `lwan`_’s trie assume it
was a match.

.. _Tries: https://en.wikipedia.org/wiki/Trie
.. _Radix tree: https://en.wikipedia.org/wiki/Radix_tree
.. _Lwan: http://github.com/lpereira/lwan
.. _hash tables: https://en.wikipedia.org/wiki/Hash_table
.. _collisions:
    https://en.wikipedia.org/wiki/Collision_(computer_science)



.. author:: default
.. categories:: none
.. tags:: data-structure,programming,lwan
.. comments::