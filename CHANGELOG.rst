
Changelog
=========

1.1.0 (2015-06-06)
------------------

* Added support for installing the manhole via the ``PYTHONMANHOLE`` environment variable.
* Added a ``strict`` install option. Set it to false to avoid getting the ``AlreadyInstalled`` exception.
* Added a ``manhole-cli`` script that emulates ``socat readline unix-connect:/tmp/manhole-1234``.

1.0.0 (2014-10-13)
------------------

* Added ``socket_path`` install option (contributed by `Nir Soffer`_).
* Added ``reinstall_delay`` install option.
* Added ``locals`` install option (contributed by `Nir Soffer`_).
* Added ``redirect_stderr`` install option (contributed by `Nir Soffer`_).
* Lots of internals cleanup (contributed by `Nir Soffer`_).

0.6.2 (2014-04-28)
------------------

* Fix OS X regression.

0.6.1 (2014-04-28)
------------------

* Support for OS X (contributed by `Saulius Menkevičius`_).

.. _Saulius Menkevičius: https://github.com/razzmatazz
.. _Nir Soffer: https://github.com/nirs
