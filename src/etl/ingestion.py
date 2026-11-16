"""Módulo de varredura agnóstica de diretórios e construção do Lakehouse.

Localiza arquivos (.csv, .txt, .xls, .xlsx, .gpkg), aplica tradução de colunas
(incluindo variáveis IBGE vXXXXX) e sanitização determinística C++ totalmente
vetorizada na carga, persistindo em Apache Parquet com DuckDB.
"""

from pathlib import Path
from typing import Dict, List
import duckdb
import geopandas as gpd
import pandas as pd

from src.etl.sanitizer import (
    converter_moeda_brl_para_float_serie,
    sanitizar_id_serie,
    sanitizar_texto_generico_serie,
    traduzir_colunas_dataframe,
)


class AgnosticDataIngestor:
    """Gerenciador do pipeline de varredura, tradução, sanitização e carga no Lakehouse."""

    EXTENSOES_SUPORTADAS = {".csv", ".txt", ".xls", ".xlsx", ".gpkg"}

    def __init__(self, data_dir: str, lakehouse_dir: str, db_path: str) -> None:
        """Inicializa os caminhos das pastas de trabalho do pipeline.

        Args:
            data_dir (str): Diretório contendo os arquivos brutos.
            lakehouse_dir (str): Diretório de destino para arquivos Parquet.
            db_path (str): Caminho do arquivo de banco de dados DuckDB.
        """
        self.data_dir = Path(data_dir)
        self.lakehouse_dir = Path(lakehouse_dir)
        self.db_path = Path(db_path)
        self.lakehouse_dir.mkdir(parents=True, exist_ok=True)

    def varrer_e_ler_arquivos(self) -> List[Path]:
        """Realiza busca recursiva em profundidade por arquivos suportados.

        Returns:
            List[Path]: Caminhos dos arquivos encontrados.
        """
        arquivos_encontrados: List[Path] = []
        for caminho in self.data_dir.rglob("*"):
            if caminho.is_file() and caminho.suffix.lower() in self.EXTENSOES_SUPORTADAS:
                arquivos_encontrados.append(caminho)
        return arquivos_encontrados

    def carregar_dataframe_bruto(self, caminho_arquivo: Path) -> pd.DataFrame:
        """Lê um arquivo do disco utilizando o scanner vetorizado C++ do DuckDB.

        Garante leitura sem exceções de codificação Unicode e baixo uso de RAM.

        Args:
            caminho_arquivo (Path): Objeto Path apontando para o arquivo.

        Returns:
            pd.DataFrame: Dados brutos carregados como texto.

        Raises:
            ValueError: Se o formato do arquivo não for suportado.
        """
        ext = caminho_arquivo.suffix.lower()

        if ext in [".csv", ".txt"]:
            path_escaped = caminho_arquivo.as_posix().replace("'", "''")
            con_temp = duckdb.connect(database=":memory:")
            df = con_temp.execute(
                f"SELECT * FROM read_csv_auto('{path_escaped}', encoding='latin-1', all_varchar=True)"
            ).df()
            con_temp.close()
            return df

        elif ext in [".xls", ".xlsx"]:
            return pd.read_excel(caminho_arquivo, dtype=str)

        elif ext == ".gpkg":
            gdf = gpd.read_file(caminho_arquivo)
            if "geometry" in gdf.columns:
                gdf["geometry_wkt"] = gdf["geometry"].apply(
                    lambda g: g.wkt if g is not None else None
                )
                gdf = gdf.drop(columns=["geometry"])
            return pd.DataFrame(gdf)

        else:
            raise ValueError(f"Extensão não suportada: {ext}")

    def sanitizar_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aplica higienização determinística cega sobre as colunas traduzidas."""
        for col in df.columns:
            col_lower = str(col).lower()

            # 1. Chaves, IDs, Códigos, Zonas, Seções, CPFs, CNPJs, Setores e Títulos
            if (
                col_lower.startswith("id_")
                or col_lower.startswith("codigo_")
                or col_lower.startswith("numero_")
                or col_lower.startswith("sigla_")
                or any(k in col_lower for k in ["ano", "zona", "secao", "cpf", "cnpj", "titulo", "cep", "setor"])
            ):
                df[col] = sanitizar_id_serie(df[col])

            # 2. Valores Monetários e Financeiros (Apenas colunas efetivamente numéricas)
            elif (
                not col_lower.startswith(("descricao_", "ds_", "data_", "dt_", "codigo_", "cd_", "tipo_", "tp_"))
                and (
                    col_lower.startswith(("valor_", "vr_", "custo_", "orcamento_"))
                    or col_lower in ["valor", "receita", "despesa", "custo", "orcamento"]
                    or any(k in col_lower for k in ["valor_despesa", "valor_receita", "valor_bem", "valor_pagamento"])
                )
            ):
                df[col] = converter_moeda_brl_para_float_serie(df[col])

            # 3. Decimais / Indicadores do Censo (Média, Percentual, Área)
            elif any(k in col_lower for k in ["area_km2", "media_moradores", "percentual_domicilios"]):
                df[col] = (
                    pd.to_numeric(df[col], errors="coerce")
                    .fillna(0.0)
                    .astype("float64")
                )

            # 4. Contagens e Inteiros (Totais, Votos, Pessoas, Domicílios, Vagas, Idade)
            elif any(k in col_lower for k in ["votos", "quantidade", "qtd", "vaga", "idade", "ordem", "total_pessoas", "total_domicilios"]):
                df[col] = (
                    pd.to_numeric(df[col], errors="coerce")
                    .fillna(0)
                    .astype("int64")
                )

            # 5. Textos Genéricos e Nomes
            else:
                df[col] = sanitizar_texto_generico_serie(df[col])

        return df
    

    def executar_pipeline_ingestao(self) -> Dict[str, str]:
        """Executa a varredura, tradução de colunas, sanitização C++, Parquet e DuckDB.

        Returns:
            Dict[str, str]: Mapeamento contendo o nome da tabela e seu arquivo Parquet.
        """
        arquivos = self.varrer_e_ler_arquivos()
        tabelas_registradas: Dict[str, str] = {}

        conn = duckdb.connect(str(self.db_path))

        for arquivo in arquivos:
            nome_tabela = arquivo.stem.lower().replace(" ", "_").replace("-", "_")

            # 1. Leitura bruta em C++
            df_bruto = self.carregar_dataframe_bruto(arquivo)

            # 2. Tradução de Colunas O(C) (Siglas e vXXXXX -> Nomes leigos concisos)
            df_traduzido = traduzir_colunas_dataframe(df_bruto)

            # 3. Sanitização determinística C++ vetorizada
            df_sanitizado = self.sanitizar_dataframe(df_traduzido)

            # 4. Persistência em Apache Parquet (Snappy)
            parquet_path = self.lakehouse_dir / f"{nome_tabela}.parquet"
            df_sanitizado.to_parquet(
                parquet_path, compression="snappy", index=False
            )

            # 5. Remoção preventiva e idempotente baseada na inspeção do catálogo de metadados
            res = conn.execute(
                "SELECT table_type FROM information_schema.tables "
                "WHERE table_schema = 'main' AND lower(table_name) = lower(?)",
                [nome_tabela],
            ).fetchone()

            if res:
                table_type = res[0]
                if table_type == "BASE TABLE":
                    conn.execute(f'DROP TABLE IF EXISTS "{nome_tabela}"')
                elif table_type == "VIEW":
                    conn.execute(f'DROP VIEW IF EXISTS "{nome_tabela}"')

            # 6. Registro oficial da Tabela no DuckDB
            conn.execute(
                f'CREATE TABLE "{nome_tabela}" AS '
                f"SELECT * FROM read_parquet('{parquet_path.as_posix()}')"
            )

            tabelas_registradas[nome_tabela] = str(parquet_path)

        conn.close()
        return tabelas_registradas