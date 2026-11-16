"""Motor de tradução e execução vetorizada SIMD C++ de SQL sobre Apache Parquet.

Realiza consultas zero-copy diretamente sobre os arquivos Parquet do Lakehouse
com baixo consumo de RAM e serialização otimizada em binário Parquet ou DataFrames.
"""

from pathlib import Path
import duckdb
import pandas as pd


class ParquetQueryEngine:
    """Motor analítico de alta performance para execução de queries sobre Parquet."""

    def __init__(self, lakehouse_dir: str = "./lakehouse_eleitoral") -> None:
        """Inicializa o motor com o diretório dos arquivos Parquet.

        Args:
            lakehouse_dir (str): Diretório onde estão os arquivos Parquet.
        """
        self.lakehouse_dir = Path(lakehouse_dir)

    def registrar_views_parquet(self, con: duckdb.DuckDBPyConnection) -> int:
        """Registra views virtuais in-memory para todos os arquivos Parquet do Lakehouse.

        Inspeciona o catálogo via information_schema para remover de forma segura
        tabelas ou views preexistentes antes de vincular as views virtuais zero-copy.

        Args:
            con (duckdb.DuckDBPyConnection): Conexão ativa com o DuckDB.

        Returns:
            int: Quantidade de views Parquet registradas com sucesso.
        """
        arquivos_parquet = list(self.lakehouse_dir.glob("*.parquet"))
        for parquet_file in arquivos_parquet:
            nome_tabela = parquet_file.stem
            path_escaped = parquet_file.as_posix().replace("'", "''")

            # Inspeciona o catálogo oficial para verificar o tipo do objeto preexistente
            res = con.execute(
                "SELECT table_type FROM information_schema.tables "
                "WHERE table_schema = 'main' AND lower(table_name) = lower(?)",
                [nome_tabela],
            ).fetchone()

            if res:
                table_type = res[0]
                if table_type == "BASE TABLE":
                    con.execute(f'DROP TABLE IF EXISTS "{nome_tabela}"')
                elif table_type == "VIEW":
                    con.execute(f'DROP VIEW IF EXISTS "{nome_tabela}"')

            con.execute(
                f'CREATE VIEW "{nome_tabela}" AS '
                f"SELECT * FROM read_parquet('{path_escaped}')"
            )
        return len(arquivos_parquet)

    def executar_para_dataframe(
        self, con: duckdb.DuckDBPyConnection, query_sql: str
    ) -> pd.DataFrame:
        """Executa a query SQL vetorizada e retorna o resultado em um DataFrame Pandas.

        Args:
            con (duckdb.DuckDBPyConnection): Conexão DuckDB.
            query_sql (str): Instrução SQL a ser executada.

        Returns:
            pd.DataFrame: Resultado da consulta.
        """
        return con.execute(query_sql).df()

    def executar_para_parquet_binario(
        self, con: duckdb.DuckDBPyConnection, query_sql: str, caminho_saida_parquet: str
    ) -> str:
        """Executa a query e persiste o resultado em binário Parquet (Snappy) via C++.

        Args:
            con (duckdb.DuckDBPyConnection): Conexão DuckDB.
            query_sql (str): Instrução SQL.
            caminho_saida_parquet (str): Caminho de saída do arquivo .parquet.

        Returns:
            str: Caminho do arquivo Parquet gerado.
        """
        path_escaped = Path(caminho_saida_parquet).as_posix().replace("'", "''")
        query_exportacion = (
            f"COPY ({query_sql}) TO '{path_escaped}' (FORMAT PARQUET, COMPRESSION SNAPPY)"
        )
        con.execute(query_exportacion)
        return caminho_saida_parquet