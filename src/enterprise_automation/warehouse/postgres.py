class PostgresWarehouse:
    def __init__(self, connection_string: str):
        self.connection_string = connection_string

    def load_rows(self, table: str, rows: list[dict]) -> int:
        raise NotImplementedError("Implement after the warehouse schema is locked.")
