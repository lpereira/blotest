Presenting EasyUI
=================


Introduction
::::::::::::

I’ve been working at `ProFUSION`_ on a project called EasyUI for the past few
months. This library is based on Google’s `V8`_ JavaScript engine and the
`Enlightenment Foundation Libraries`_ and aims to diminish the hurdle in
writing native applications for the forthcoming `Tizen`_ platform.

EFL itself – specially its UI toolkit, Elementary – follows a pretty
traditional approach to creating applications: the library user must know how
to join all bits and pieces, which often leads to common code that is written
and rewritten in each new application.

By observing common patterns and providing an uniform `MVC`_ interface,
EasyUI parts from this traditional approach and offers a new way to create
applications using EFL.

Before talking about code, let me show a video (best viewed in HD) of some
sample EasyUI applications being executed:


Brief overview of an EasyUI app
:::::::::::::::::::::::::::::::

An app begins with a simple call to ``EUI.app()``, passing at least one parameter:
    the main view-controller. The other parameter is an optional object that
    contains application settings, such as the theme or window titles. EasyUI
    applications are contained inside one window only, since the main focus
    are apps for mobile devices with stacked lists and the eventual popup
    that appears on top of the content.

The code below shows a typical controller-view; explanation will follow.

.. code-block:: javascript

    MainController = EUI.ListController({
        title: 'My Favorite Fruits',
        model: new ArrayModel(['Pear', 'Banana', 'Uvaia']),
        itemAtIndex: function(index) {
                return {
                        text: this.model.itemAtIndex(index)
                };
        },
        selectedItemAtIndex: function(index) {
                var fruit = this.model.itemAtIndex(index);
                this.pushController(new FruitController(fruit));
        },
        navigationBarItems: { right: 'Add' },
        selectedNavigationBarItem: function(item) {
                if (item === 'Add')
                        this.pushController(new AddFruitController);
        }
    });

Lots of things happens with the declaration of ``MainController``. Of note:

-   As opposed to the traditional way of laying out components on screen
    with EFL, controllers implements the basic user interface and the
    application developer focuses only on defining behavior.
-   Attributes can be functions, which will be called whenever EasyUI
    needs them. For instance, one could change the title based on how many
    fruits were in the model, by writing a ``title`` function like so:

.. code-block:: javascript

    function() {
        if (this.model.length() == 1)
                return "My Favorite Fruit";
        return "My Favourite Fruits";
    }

-   ``MainController`` is derived from ``ListController``. This means
    that it follows a *collection* contract, and must implement methods like
    ``itemAtIndex`` and ``selectedItemAtIndex``, as well as providing a
    ``model`` attribute.
-   One could simply swap ``ListController`` for ``GridController`` if a
    grid layout were to be more appropriate for this particular application.
-   In addition to the basic *contract*, controllers might sign for more;
    for instance by declaring ``navigationBarItems``, one is required to
    implement ``selectedNavigationBarItem``.

Behind the scenes, the framework will initialize the EFL, create the window
and required widgets, listen to callbacks – and call the application code in
appropriate moments.

The next post in this series will show the anatomy of a `Reddit`_ client.


Show me the code
::::::::::::::::

We’re just working on some licensing issues right now. This should be
released as an open source project. As soon as this is cleared up, EasyUI
should hit Enlightenment’s SVN repository.

.. _ProFUSION: http://profusion.mobi
.. _V8: http://code.google.com/p/v8
.. _Enlightenment Foundation Libraries: http://enlightenment.org
.. _Tizen: http://tizen.org
.. _MVC:
    https://en.wikipedia.org/wiki/Model%E2%80%93view%E2%80%93controller
.. _Reddit: http://reddit.com/



.. author:: default
.. categories:: none
.. tags:: profusion,efl,javascript,programming,tizen
.. comments::