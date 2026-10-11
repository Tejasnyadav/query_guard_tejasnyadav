from dataclasses import dataclass


 

from psycopg_pool import ConnectionPool


 

from app.config import Settings



 

@dataclass(slots=True)

class DatabasePools:

    warehouse: ConnectionPool

    app: ConnectionPool


 

    def close(self) -> None:

        self.warehouse.close()

        self.app.close()



 

def create_database_pools(settings: Settings) -> DatabasePools:

    common_kwargs = {

        "autocommit": True,

        "connect_timeout": settings.database_connect_timeout_seconds,

    }


 

    warehouse_pool = ConnectionPool(

        conninfo=settings.warehouse_database_url,

        min_size=settings.warehouse_pool_min_size,

        max_size=settings.warehouse_pool_max_size,

        kwargs=common_kwargs,

        open=False,

        name="queryguard-warehouse",

    )

    app_pool = ConnectionPool(

        conninfo=settings.app_database_url,

        min_size=settings.app_pool_min_size,

        max_size=settings.app_pool_max_size,

        kwargs=common_kwargs,

        open=False,

        name="queryguard-app",

    )


 

    try:

        warehouse_pool.open()

        app_pool.open()

        warehouse_pool.wait(timeout=settings.pool_wait_timeout_seconds)

        app_pool.wait(timeout=settings.pool_wait_timeout_seconds)

    except Exception:

        warehouse_pool.close()

        app_pool.close()

        raise


 

    return DatabasePools(warehouse=warehouse_pool, app=app_pool)


 