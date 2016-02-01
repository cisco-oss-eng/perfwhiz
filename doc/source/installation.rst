============
Installation
============

perfwhiz comes with two scripts, perfcap.py and perfmap.py. Normally,
perfcap.py will be installed on the target node for capturing the perf data,
perfmap.py can be ran from any machine to plot different types of chart from the capture data.

Both scripts are available in PyPI, and can be installed using either
"pip install" or source code based installation. In either option of
installation, please have python and python-dev installed.

Ubuntu/Debian based:

.. code-block:: bash

    $ sudo apt-get install python-dev python-pip python-virtualenv

RHEL/Fedora/CentOS based:

.. code-block:: bash

    $ sudo yum install gcc python-devel python-pip python-virtualenv

You may also want to create a python virtual environment if you prefer to have
isolation of python installations (this is recommended but optional):

.. code-block:: bash

    $ virtualenv pft
    $ source pft/bin/activate

Remember to activate your virtual environment every time before installing
or using the tool.

perfcap.py
----------

perfcap.py is a wrapper around Linux perf tool. In order to run perfcap.py,
the native perf tool must be built with Python extension. Run below
command to check whether this feature is pre-built in the perf version provided by your
distro::

    $ sudo perf script -g python

If you see below message, congratulations! It is ready to use out-of box::

    generated Python script: perf-script.py

If you see below message, unfortunately you have to do some extra works to
rebuild the tool::

    $ sudo perf script -g python
    Python scripting not supported.  Install libpython and rebuild perf to enable it.
    For example:
      # apt-get install python-dev (ubuntu)
      # yum install python-devel (Fedora)
      etc.

Normally, if you are using a RHEL/CentOS distro, the tool from official
repository has been built with Python extension already. If you are
using a Ubuntu distro, unfortunately you have to rebuild perf and enable
the Python scripting extension. Refer to
`here <http://askubuntu.com/questions/577768/how-can-i-make-perf-script-g-python-work>`_
for the details on the steps to follow to rebuild perf.

Installation from PyPI will be as easy as::

    $ pip install perfwhiz

Installation from source code be as easy as:

.. code-block:: bash

    $ git clone https://github.com/cisco-oss-eng/perfwhiz.git
    $ cd perfwhiz
    $ pip install -e.

Once installation is finished, you should be able to verify the installation
by doing::

    $ python perfcap.py -h

perfmap.py
----------

perfmap, the analyzer tool of perfwhiz, will do the data analysis based on
different scheduler events, and draw the charts to present them. It is
using Pandas, Numpy to perform data processing, Bokeh and D3.js for charts.

Installation from PyPI will be as easy as::

    $ pip install perfwhiz[analyzer]

Installation from source code be as easy as:

.. code-block:: bash

    $ git clone https://github.com/cisco-oss-eng/perfwhiz.git
    $ cd perfwhiz
    $ pip install -e.[analyzer]

Once installation is finished, you should be able to verify the installation
by doing::

    $ python perfmap.py -h
