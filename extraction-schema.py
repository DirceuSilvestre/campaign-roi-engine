"""Script para extração dinâmica e independente do schema do Lakehouse Eleitoral.

Inspeciona em tempo real todas as tabelas e views Parquet persistidas em 
./lakehouse_eleitoral/ e gera o arquivo físico schema_lakehouse.json contendo 
o mapeamento de tabelas, colunas descritivas e tipos de dados (VARCHAR, DOUBLE, BIGINT).
"""

import json
from pathlib import Path
from typing import Any, Dict, List
import duckdb


def extrair_schema_lakehouse(lakehouse_dir: str, output_json: str) -> Dict[str, Any]:
    """Varre os arquivos Parquet do Lakehouse e extrai o schema completo.

    Args:
        lakehouse_dir (str): Diretório onde estão os arquivos .parquet.
        output_json (str): Caminho para gravação do arquivo JSON de saída.

    Returns:
        Dict[str, Any]: Dicionário contendo a estrutura do schema extraído.
    """
    dir_path = Path(lakehouse_dir)
    arquivos_parquet = list(dir_path.glob("*.parquet"))

    schema_tabelas: Dict[str, List[Dict[str, str]]] = {}
    conn = duckdb.connect(database=":memory:")

    for parquet_file in arquivos_parquet:
        nome_tabela = parquet_file.stem
        path_escaped = parquet_file.as_posix().replace("'", "''")

        # Inspeciona metadados e tipos de dados diretamente do Parquet
        colunas_info = conn.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{path_escaped}')"
        ).fetchall()

        colunas_lista = [
            {"coluna": col[0], "tipo": str(col[1])} for col in colunas_info
        ]

        schema_tabelas[nome_tabela] = colunas_lista

    conn.close()

    payload = {
        "contexto": "Schema Estruturado do Lakehouse Eleitoral C-Level",
        "total_tabelas": len(schema_tabelas),
        "tabelas": schema_tabelas,
    }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)

    return payload


def main() -> None:
    """Executa o re-escaneamento dinâmico e gera o schema_lakehouse.json."""
    print("=" * 70)
    print(" EXTRAÇÃO DINÂMICA DE SCHEMA DO LAKEHOUSE (schema_lakehouse.json)")
    print("=" * 70)

    lakehouse_dir = "./lakehouse_eleitoral"
    output_json = "./schema_lakehouse.json"

    schema = extrair_schema_lakehouse(
        lakehouse_dir=lakehouse_dir, output_json=output_json
    )

    print(
        f"\n[SUCESSO] Mapeamento concluído! {schema['total_tabelas']} tabelas "
        f"exportadas para '{output_json}'.\n"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()