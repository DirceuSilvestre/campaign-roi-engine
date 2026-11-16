"""Script de entrada para execução do pipeline de ingestão determinística."""

from src.etl.ingestion import AgnosticDataIngestor


def main() -> None:
    """Inicializa os caminhos e executa a ingestão completa."""
    print("=" * 70)
    print("INICIANDO INGESTÃO E SANITIZAÇÃO DETERMINÍSTICA (ETL)")
    print("=" * 70)

    data_dir = "./data"
    lakehouse_dir = "./lakehouse_eleitoral"
    db_path = "./lakehouse_eleitoral/analytics.duckdb"

    ingestor = AgnosticDataIngestor(
        data_dir=data_dir,
        lakehouse_dir=lakehouse_dir,
        db_path=db_path
    )

    tabelas = ingestor.executar_pipeline_ingestao()

    print(f"\n[SUCESSO] Processamento concluído! {len(tabelas)} tabela(s) gerada(s):\n")
    for tabela, parquet_path in tabelas.items():
        print(f" -> Tabela: '{tabela}' | Arquivo Parquet: {parquet_path}")

    print("=" * 70)
    print()


if __name__ == "__main__":
    main()