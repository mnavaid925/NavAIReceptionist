"""Project package.

Installs the PyMySQL shim so Django's `mysql` backend can talk to MySQL/MariaDB
(XAMPP) without the compiled `mysqlclient` extension. This must run before Django
loads the database backend, which is why it lives here rather than in settings.
"""
import pymysql

pymysql.install_as_MySQLdb()
