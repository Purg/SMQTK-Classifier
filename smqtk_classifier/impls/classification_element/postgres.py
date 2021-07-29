import logging
import pickle
from typing import Any, Dict, Hashable, Optional
import warnings
from threading import RLock

from smqtk_dataprovider.utils.postgres import (
    PsqlConnectionHelper,
)

from smqtk_classifier.exceptions import NoClassificationError
from smqtk_classifier.interfaces.classification_element import (
    ClassificationElement,
    CLASSIFICATION_DICT_T,
    CLASSIFICATION_MAP_T
)


LOG = logging.getLogger(__name__)
GLOBAL_PSQL_TABLE_CREATE_RLOCK = RLock()


# Try to import required modules
try:
    import psycopg2  # type: ignore
except ImportError:
    warnings.warn(
        "psycopg2 not importable: PostgresClassificationElement will not be"
        "usable."
    )
    psycopg2 = None


class PostgresClassificationElement (ClassificationElement):  # lgtm [py/missing-equals]
    """
    PostgreSQL database backed classification element.

    Requires a table of at least 3 fields (column names configurable):

        - type-name :: text
        - uuid :: text
        - classification-binary :: bytea

    We require that storage tables treat uuid AND type string columns as
    primary keys. The type and uuid columns should be of the ``text`` type.
    The binary column should be of the ``bytea`` type.

    Default argument values assume a local PostgreSQL database with a table
    created via the
    ``etc/smqtk/postgres/classification_element/example_table_init.sql``
    file (relative to the SMQTK source tree or install root).

    NOTES:
        - Not all uuid types used here are necessarily of the ``uuid.UUID``
          type, thus the recommendation to use a ``text`` type for the
          column. For certain specific use cases they may be proper
          ``uuid.UUID`` instances or strings, but this cannot be generally
          assumed.

    :param type_name: Name of the type of classifier this classification was
        generated by.
    :param uuid: Unique ID reference of the classification
    :param table_name: String label of the database table to use.
    :param type_col: The column label for classification type name storage.
    :param uuid_col: The column label for classification UUID storage
    :param classification_col: The column label for classification binary
        storage.
    :param db_name: The name of the database to connect to.
    :param db_host: Host address of the Postgres server. If None, we
        assume the server is on the local machine and use the UNIX socket.
        This might be a required field on Windows machines (not tested yet).
    :param db_port: Port the Postgres server is exposed on. If None, we
        assume the default port (5423).
    :param db_user: Postgres user to connect as. If None, postgres
        defaults to using the current accessing user account name on the
        operating system.
    :param db_pass: Password for the user we're connecting as. This may be
        None if no password is to be used.
    :param pickle_protocol: Pickling protocol to use. We will use -1 by
        default (latest version, probably binary).
    :param create_table: If this instance should try to create the storing
        table before actions are performed against it. If the configured
        user does not have sufficient permissions to create the table and it
        does not currently exist, an exception will be raised.
    """

    __slots__ = ('table_name', 'type_col', 'uuid_col', 'classification_col',
                 'db_name', 'db_host', 'db_port', 'db_user', 'db_pass',
                 'pickle_protocol', 'create_table')

    UPSERT_TABLE_TMPL = ' '.join("""
        CREATE TABLE IF NOT EXISTS {table_name:s} (
          {type_col:s} TEXT NOT NULL
          {uuid_col:s} TEXT NOT NULL,
          {classification_col:s} BYTEA NOT NULL,
          PRIMARY KEY ({type_col:s}, {uuid_col:s})
        );
    """.split())

    # Known psql version compatibility: 9.4
    SELECT_TMPL = ' '.join("""
        SELECT {classification_col:s}
          FROM {table_name:s}
          WHERE {type_col:s} = %(type_val)s
            AND {uuid_col:s} = %(uuid_val)s
        ;
    """.split())

    # Known psql version compatibility: 9.4
    UPSERT_TMPL = ' '.join("""
        WITH upsert AS (
          UPDATE {table_name:s}
            SET {classification_col:s} = %(classification_val)s
            WHERE {type_col:s} = %(type_val)s
              AND {uuid_col:s} = %(uuid_val)s
            RETURNING *
          )
        INSERT INTO {table_name:s}
          ({type_col:s}, {uuid_col:s}, {classification_col:s})
          SELECT %(type_val)s, %(uuid_val)s, %(classification_val)s
            WHERE NOT EXISTS (SELECT * FROM upsert);
    """.split())

    def __init__(
        self,
        type_name: str,
        uuid: Hashable,
        table_name: str = 'classifications',
        type_col: str = 'type_name',
        uuid_col: str = 'uid',
        classification_col: str = 'classification',
        db_name: str = 'postgres',
        db_host: Optional[str] = None,
        db_port: Optional[int] = None,
        db_user: Optional[str] = None,
        db_pass: Optional[str] = None,
        pickle_protocol: int = -1,
        create_table: bool = True
    ):
        super(PostgresClassificationElement, self).__init__(type_name, uuid)

        self.table_name = table_name
        self.type_col = type_col
        self.uuid_col = uuid_col
        self.classification_col = classification_col

        self.pickle_protocol = pickle_protocol
        self.create_table = create_table

        self._psql_helper = PsqlConnectionHelper(
            db_name, db_host, db_port, db_user, db_pass, 10,
            GLOBAL_PSQL_TABLE_CREATE_RLOCK
        )

        self._psql_helper.set_table_upsert_sql(
            self.UPSERT_TABLE_TMPL.format(**dict(
                table_name=self.table_name,
                type_col=self.type_col,
                uuid_col=self.uuid_col,
                classification_col=self.classification_col,
            )))

    @classmethod
    def is_usable(cls) -> bool:
        return psycopg2 is not None

    def get_config(self) -> Dict[str, Any]:
        return {
            "table_name": self.table_name,
            "type_col": self.type_col,
            "uuid_col": self.uuid_col,
            "classification_col": self.classification_col,

            "db_name": self._psql_helper.db_name,
            "db_host": self._psql_helper.db_host,
            "db_port": self._psql_helper.db_port,
            "db_user": self._psql_helper.db_user,
            "db_pass": self._psql_helper.db_pass,

            "pickle_protocol": self.pickle_protocol,
            "create_table": self.create_table,
        }

    def __getstate__(self) -> Any:
        s = self.get_config()
        s['parent'] = super(PostgresClassificationElement, self).__getstate__()
        return s

    def __setstate__(self, state: Any) -> None:
        super(PostgresClassificationElement, self).__setstate__(
            state['parent']
        )
        self.table_name = state['table_name']
        self.type_col = state['type_col']
        self.uuid_col = state['uuid_col']
        self.classification_col = state['classification_col']

        self._psql_helper.db_name = state['db_name']
        self._psql_helper.db_host = state['db_host']
        self._psql_helper.db_port = state['db_port']
        self._psql_helper.db_user = state['db_user']
        self._psql_helper.db_pass = state['db_pass']

        self.pickle_protocol = state['pickle_protocol']
        self.create_table = state['create_table']

    def has_classifications(self) -> bool:
        try:
            return bool(self.get_classification())
        except NoClassificationError:
            return False

    def get_classification(self) -> CLASSIFICATION_DICT_T:
        q_select = self.SELECT_TMPL.format(**dict(
            table_name=self.table_name,
            type_col=self.type_col,
            uuid_col=self.uuid_col,
            classification_col=self.classification_col,
        ))
        q_select_values = {
            "type_val": self.type_name,
            "uuid_val": str(self.uuid)
        }

        def cb(cur: psycopg2.extensions.cursor) -> None:
            cur.execute(q_select, q_select_values)

        r = list(self._psql_helper.single_execute(cb, yield_result_rows=True))
        if not r:
            raise NoClassificationError("No PSQL backed classification for "
                                        "label='%s' uuid='%s'"
                                        % (self.type_name, str(self.uuid)))
        else:
            c = pickle.loads(r[0])
            return c

    def set_classification(
        self,
        m: Optional[CLASSIFICATION_MAP_T] = None,
        **kwds: float
    ) -> CLASSIFICATION_DICT_T:
        m = super(PostgresClassificationElement, self)\
            .set_classification(m, **kwds)

        q_upsert = self.UPSERT_TMPL.strip().format(**{
            "table_name": self.table_name,
            "classification_col": self.classification_col,
            "type_col": self.type_col,
            "uuid_col": self.uuid_col,
        })
        q_upsert_values = {
            "classification_val":
                psycopg2.Binary(pickle.dumps(m, self.pickle_protocol)),
            "type_val": self.type_name,
            "uuid_val": str(self.uuid),
        }

        def cb(cur: psycopg2.extensions.cursor) -> None:
            cur.execute(q_upsert, q_upsert_values)

        list(self._psql_helper.single_execute(cb))

        return m
