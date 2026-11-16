"""Módulo de conexão e gerenciamento do ciclo de vida com o banco de dados DuckDB.

Gerencia sessões, aplica configurações de performance C++ (threads/RAM) e orquestra
a execução resiliente de queries SQL com suporte a auto-reparo sintático em 2ª tentativa.
"""

import os
from pathlib import Path
from typing import Optional
import duckdb
import pandas as pd

from src.database.auto_repair import SQLAutoRepair
from src.database.parquet_engine import ParquetQueryEngine
from src.database.schema_manager import SchemaManager


class DatabaseConnection:
    """Gerenciador centralizado de conexão e execução do DuckDB."""

    def __init__(
        self,
        db_path: str = "./lakehouse_eleitoral/analytics.duckdb",
        schema_json_path: str = "./schema_lakehouse.json",
        lakehouse_dir: str = "./lakehouse_eleitoral",
    ) -> None:
        """Inicializa a infraestrutura de conexão, schema e auto-reparo.

        Args:
            db_path (str): Caminho do banco DuckDB.
            schema_json_path (str): Caminho do arquivo schema_lakehouse.json.
            lakehouse_dir (str): Diretório dos arquivos Parquet.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.schema_manager = SchemaManager(schema_json_path)
        self.auto_repair = SQLAutoRepair(self.schema_manager)
        self.parquet_engine = ParquetQueryEngine(lakehouse_dir)

    def obter_conexao(self) -> duckdb.DuckDBPyConnection:
        """Abre uma conexão DuckDB otimizada e registra as views Parquet.

        Returns:
            duckdb.DuckDBPyConnection: Conexão ativa com o banco.
        """
        con = duckdb.connect(str(self.db_path))
        num_threads = os.cpu_count() or 4
        con.execute(f"PRAGMA threads={num_threads}")
        self.parquet_engine.registrar_views_parquet(con)
        return con

    def executar_consulta(
        self, query_sql: str, caminho_export_parquet: Optional[str] = None
    ) -> pd.DataFrame:
        """Executa consulta SQL com resiliência e auto-reparo automatizado em 2ª tentativa.

        Aplica as regras do dialeto DuckDB (harmonização com strip_accents,
        comparação exata de chaves e COALESCE em somas).

        Args:
            query_sql (str): Query SQL enviada para processamento.
            caminho_export_parquet (Optional[str]): Se informado, salva o resultado em Parquet.

        Returns:
            pd.DataFrame: Resultado da consulta processada.

        Raises:
            RuntimeError: Se a consulta falhar persistindo na 2ª tentativa.
        """
        con = self.obter_conexao()

        try:
            # 1ª Tentativa de Execução Nativa C++
            if caminho_export_parquet:
                self.parquet_engine.executar_para_parquet_binario(
                    con, query_sql, caminho_export_parquet
                )
            df_resultado = self.parquet_engine.executar_para_dataframe(con, query_sql)
            con.close()
            return df_resultado

        except (
            duckdb.ParserException,
            duckdb.CatalogException,
            duckdb.BinderException,
            duckdb.Error,
        ) as e_erro:
            mensagem_erro = str(e_erro)

            # Auto-reparo sintático e reescrita determinística para 2ª Tentativa
            # Em src/database/connection.py -> executar_consulta

            try:
                df_resultado = self.parquet_engine.executar_para_dataframe(con, query_sql)
                return df_resultado
            except Exception as e:
                # Garantir que o raise esteja dentro do bloco except
                raise e

            try:
                # 2ª Tentativa de Execução
                if caminho_export_parquet:
                    self.parquet_engine.executar_para_parquet_binario(
                        con, query_reparada, caminho_export_parquet
                    )
                df_resultado = self.parquet_engine.executar_para_dataframe(
                    con, query_reparada
                )
                con.close()
                return df_resultado

            except Exception as e_persiste:
                con.close()
                raise RuntimeError(
                    f"[FALHA ESTRITA] Query falhou na 1ª tentativa ({mensagem_erro}) "
                    f"e a 2ª tentativa com auto-reparo também falhou ({motivo}). "
                    f"Erro final: {str(e_persiste)}"
                ) from e_persiste