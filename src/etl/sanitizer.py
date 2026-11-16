"""Módulo de sanitização determinística e tradução de colunas para a camada ETL.

Disponibiliza o dicionário de mapeamento de siglas eleitorais e geográficas
(incluindo o dicionário do IBGE Censo/Malha Agregados vXXXXX), funções vetorizadas
em C++ de alta performance para Séries e sanitizadores escalares.
"""

import re
from typing import Any, Dict
import numpy as np
import pandas as pd


# Dicionário determinístico de tradução de siglas brutas (TSE / IBGE Censo vXXXXX)
MAPA_TRADUCAO_COLUNAS: Dict[str, str] = {
    # Censo IBGE - Malha Agregados e Variáveis vXXXXX
    "V0001": "total_pessoas",
    "V0002": "total_domicilios",
    "V0003": "total_domicilios_particulares",
    "V0004": "total_domicilios_coletivos",
    "V0005": "media_moradores_domicilios_particulares_ocupados",
    "V0006": "percentual_domicilios_particulares_ocupados_imputados",
    "V0007": "total_domicilios_particulares_ocupados",
    "V001": "total_pessoas",
    "V002": "total_domicilios",
    "V003": "total_domicilios_particulares",
    "V004": "total_domicilios_coletivos",
    "V005": "media_moradores_domicilios_particulares_ocupados",
    "V006": "percentual_domicilios_particulares_ocupados_imputados",
    "V007": "total_domicilios_particulares_ocupados",
    "CD_SETOR": "codigo_setor",
    "SITUACAO": "situacao_setor",
    "CD_SITUACAO": "codigo_situacao_setor",
    "CD_TIPO": "codigo_tipo_setor",
    "CD_NU": "codigo_nucleo_urbano",
    "NM_NU": "nome_nucleo_urbano",
    "CD_FCU": "codigo_favela_comunidade_urbana",
    "NM_FCU": "nome_favela_comunidade_urbana",
    "CD_AGLOM": "codigo_aglomerado",
    "NM_AGLOM": "nome_aglomerado",
    "CD_SUBDIS": "codigo_subdistrito",

    # Metadados e Controle
    "DT_GERACAO": "data_geracao",
    "HH_GERACAO": "hora_geracao",
    "ANO_ELEICAO": "ano_eleicao",
    "AA_ELEICAO": "ano_eleicao",
    "CD_TIPO_ELEICAO": "codigo_tipo_eleicao",
    "NM_TIPO_ELEICAO": "nome_tipo_eleicao",
    "CD_ELEICAO": "codigo_eleicao",
    "DS_ELEICAO": "descricao_eleicao",
    "DT_ELEICAO": "data_eleicao",
    "NR_TURNO": "turno",
    "ST_TURNO": "turno",
    "TP_ABRANGENCIA": "tipo_abrangencia",
    "SG_UF": "sigla_uf",
    "SG_UE": "sigla_ue",
    "NM_UE": "nome_ue",
    "CD_MUNICIPIO": "codigo_municipio",
    "CD_MUN": "codigo_municipio",
    "NM_MUNICIPIO": "nome_municipio",
    "NM_MUN": "nome_municipio",
    "NR_ZONA": "numero_zona",
    "NR_SECAO": "numero_secao",

    # Cargos e Candidaturas
    "CD_CARGO": "codigo_cargo",
    "DS_CARGO": "descricao_cargo",
    "SQ_CANDIDATO": "id_candidato",
    "NR_CANDIDATO": "numero_candidato",
    "NM_CANDIDATO": "nome_candidato",
    "NM_URNA_CANDIDATO": "nome_urna_candidato",
    "NM_SOCIAL_CANDIDATO": "nome_social_candidato",
    "NR_CPF_CANDIDATO": "cpf_candidato",
    "NR_CPF_VICE_CANDIDATO": "cpf_vice_candidato",
    "DS_EMAIL": "email_candidato",
    "CD_SITUACAO_CANDIDATURA": "codigo_situacao_candidatura",
    "DS_SITUACAO_CANDIDATURA": "descricao_situacao_candidatura",
    "TP_AGREMIACAO": "tipo_agremiacao",
    "NR_PARTIDO": "numero_partido",
    "SG_PARTIDO": "sigla_partido",
    "NM_PARTIDO": "nome_partido",
    "NR_FEDERACAO": "numero_federacao",
    "NM_FEDERACAO": "nome_federacao",
    "SG_FEDERACAO": "sigla_federacao",
    "DS_COMPOSICAO_FEDERACAO": "composicao_federacao",
    "SQ_COLIGACAO": "id_coligacao",
    "NM_COLIGACAO": "nome_coligacao",
    "DS_COMPOSICAO_COLIGACAO": "composicao_coligacao",
    "SG_UF_NASCIMENTO": "uf_nascimento",
    "DT_NASCIMENTO": "data_nascimento",
    "NR_TITULO_ELEITORAL_CANDIDATO": "titulo_eleitoral",
    "CD_GENERO": "codigo_genero",
    "DS_GENERO": "descricao_genero",
    "CD_GRAU_INSTRUCAO": "codigo_grau_instrucao",
    "DS_GRAU_INSTRUCAO": "descricao_grau_instrucao",
    "CD_ESTADO_CIVIL": "codigo_estado_civil",
    "DS_ESTADO_CIVIL": "descricao_estado_civil",
    "CD_COR_RACA": "codigo_cor_raca",
    "DS_COR_RACA": "descricao_cor_raca",
    "CD_OCUPACAO": "codigo_ocupacao",
    "DS_OCUPACAO": "descricao_ocupacao",
    "CD_SIT_TOT_TURNO": "codigo_situacao_turno",
    "DS_SIT_TOT_TURNO": "descricao_situacao_turno",

    # Bens de Candidato
    "NR_ORDEM_BEM_CANDIDATO": "ordem_bem",
    "CD_TIPO_BEM_CANDIDATO": "codigo_tipo_bem",
    "DS_TIPO_BEM_CANDIDATO": "descricao_tipo_bem",
    "DS_BEM_CANDIDATO": "descricao_bem",
    "VR_BEM_CANDIDATO": "valor_bem",
    "DT_ULT_ATUAL_BEM_CANDIDATO": "data_atualizacao_bem",
    "HH_ULT_ATUAL_BEM_CANDIDATO": "hora_atualizacao_bem",

    # Dados Complementares de Candidato
    "CD_DETALHE_SITUACAO_CAND": "codigo_detalhe_situacao",
    "DS_DETALHE_SITUACAO_CAND": "descricao_detalhe_situacao",
    "CD_NACIONALIDADE": "codigo_nacionalidade",
    "DS_NACIONALIDADE": "descricao_nacionalidade",
    "CD_MUNICIPIO_NASCIMENTO": "codigo_municipio_nascimento",
    "NM_MUNICIPIO_NASCIMENTO": "nome_municipio_nascimento",
    "NR_IDADE_DATA_POSSE": "idade_data_posse",
    "ST_QUILOMBOLA": "status_quilombola",
    "CD_ETNIA_INDIGENA": "codigo_etnia_indigena",
    "DS_ETNIA_INDIGENA": "descricao_etnia_indigena",
    "VR_DESPESA_MAX_CAMPANHA": "valor_despesa_maxima",
    "ST_REELEICAO": "status_reeleicao",
    "ST_DECLARAR_BENS": "status_declaracao_bens",
    "NR_PROTOCOLO_CANDIDATURA": "numero_protocolo",
    "NR_PROCESSO": "numero_processo",
    "CD_SITUACAO_CANDIDATO_PLEITO": "codigo_situacao_pleito",
    "DS_SITUACAO_CANDIDATO_PLEITO": "descricao_situacao_pleito",
    "CD_SITUACAO_CANDIDATO_URNA": "codigo_situacao_urna",
    "DS_SITUACAO_CANDIDATO_URNA": "descricao_situacao_urna",
    "ST_CANDIDATO_INSERIDO_URNA": "status_inserido_urna",
    "NM_TIPO_DESTINACAO_VOTOS": "tipo_destinacao_votos",
    "CD_SITUACAO_CANDIDATO_TOT": "codigo_situacao_totalizacao",
    "DS_SITUACAO_CANDIDATO_TOT": "descricao_situacao_totalizacao",
    "ST_PREST_CONTAS": "status_prestacao_contas",
    "ST_SUBSTITUIDO": "status_substituido",
    "SQ_SUBSTITUIDO": "id_substituido",
    "SQ_ORDEM_SUPLENCIA": "ordem_suplencia",
    "DT_ACEITE_CANDIDATURA": "data_aceite_candidatura",
    "CD_SITUACAO_JULGAMENTO": "codigo_situacao_julgamento",
    "DS_SITUACAO_JULGAMENTO": "descricao_situacao_julgamento",
    "CD_SITUACAO_JULGAMENTO_PLEITO": "codigo_situacao_julgamento_pleito",
    "DS_SITUACAO_JULGAMENTO_PLEITO": "descricao_situacao_julgamento_pleito",
    "CD_SITUACAO_JULGAMENTO_URNA": "codigo_situacao_julgamento_urna",
    "DS_SITUACAO_JULGAMENTO_URNA": "descricao_situacao_julgamento_urna",
    "CD_SITUACAO_CASSACAO": "codigo_situacao_cassacao",
    "DS_SITUACAO_CASSACAO": "descricao_situacao_cassacao",
    "CD_SITUACAO_CASSACAO_MIDIA": "codigo_situacao_cassacao_midia",
    "DS_SITUACAO_CASSACAO_MIDIA": "descricao_situacao_cassacao_midia",
    "CD_SITUACAO_DCONST_DIPLOMA": "codigo_situacao_diploma",
    "DS_SITUACAO_DCONST_DIPLOMA": "descricao_situacao_diploma",
    "CD_SITUACAO_DIPLOMA": "codigo_situacao_diploma",
    "DS_SITUACAO_DIPLOMA": "descricao_situacao_diploma",
    "DT_DIPLOMACAO": "data_diplomacao",
    "CD_SITUACAO_DIPLOMACAO": "codigo_situacao_diplomacao",
    "DS_SITUACAO_DIPLOMACAO": "descricao_situacao_diplomacao",
    "ST_IMPUGNADO": "status_impugnado",
    "CD_GENERO_FEFC": "codigo_genero_fefc",
    "DS_GENERO_FEFC": "descricao_genero_fefc",
    "CD_COR_RACA_FEFC": "codigo_cor_raca_fefc",
    "DS_COR_RACA_FEFC": "descricao_cor_raca_fefc",

    # Vagas e Coligações
    "CD_SITUACAO_LEGENDA": "codigo_situacao_legenda",
    "DS_SITUACAO": "descricao_situacao",
    "DT_POSSE": "data_posse",
    "QT_VAGA": "quantidade_vagas",
    "NR_ORDEM_REDE_SOCIAL": "ordem_rede_social",
    "DS_URL": "url_rede_social",

    # Finanças e Prestação de Contas
    "TP_PRESTACAO_CONTAS": "tipo_prestacao_contas",
    "DT_PRESTACAO_CONTAS": "data_prestacao_contas",
    "SQ_PRESTADOR_CONTAS": "id_prestador_contas",
    "NR_CNPJ_PRESTADOR_CONTA": "cnpj_prestador_contas",
    "CD_TIPO_FORNECEDOR": "codigo_tipo_fornecedor",
    "DS_TIPO_FORNECEDOR": "descricao_tipo_fornecedor",
    "CD_CNAE_FORNECEDOR": "codigo_cnae_fornecedor",
    "DS_CNAE_FORNECEDOR": "descricao_cnae_fornecedor",
    "NR_CPF_CNPJ_FORNECEDOR": "cpf_cnpj_fornecedor",
    "NM_FORNECEDOR": "nome_fornecedor",
    "NM_FORNECEDOR_RFB": "nome_fornecedor_rfb",
    "CD_ESFERA_PART_FORNECEDOR": "codigo_esfera_partidaria_fornecedor",
    "DS_ESFERA_PART_FORNECEDOR": "descricao_esfera_partidaria_fornecedor",
    "SG_UF_FORNECEDOR": "sigla_uf_fornecedor",
    "CD_MUNICIPIO_FORNECEDOR": "codigo_municipio_fornecedor",
    "NM_MUNICIPIO_FORNECEDOR": "nome_municipio_fornecedor",
    "SQ_CANDIDATO_FORNECEDOR": "id_candidato_fornecedor",
    "NR_CANDIDATO_FORNECEDOR": "numero_candidato_fornecedor",
    "CD_CARGO_FORNECEDOR": "codigo_cargo_fornecedor",
    "DS_CARGO_FORNECEDOR": "descricao_cargo_fornecedor",
    "NR_PARTIDO_FORNECEDOR": "numero_partido_fornecedor",
    "SG_PARTIDO_FORNECEDOR": "sigla_partido_fornecedor",
    "NM_PARTIDO_FORNECEDOR": "nome_partido_fornecedor",
    "DS_TIPO_DOCUMENTO": "descricao_tipo_documento",
    "NR_DOCUMENTO": "numero_documento",
    "CD_ORIGEM_DESPESA": "codigo_origem_despesa",
    "DS_ORIGEM_DESPESA": "descricao_origem_despesa",
    "SQ_DESPESA": "id_despesa",
    "DT_DESPESA": "data_despesa",
    "DS_DESPESA": "descricao_despesa",
    "VR_DESPESA_CONTRATADA": "valor_despesa_contratada",
    "CD_FONTE_DESPESA": "codigo_fonte_despesa",
    "DS_FONTE_DESPESA": "descricao_fonte_despesa",
    "CD_NATUREZA_DESPESA": "codigo_natureza_despesa",
    "DS_NATUREZA_DESPESA": "descricao_natureza_despesa",
    "CD_ESPECIE_RECURSO": "codigo_especie_recurso",
    "DS_ESPECIE_RECURSO": "descricao_especie_recurso",
    "SQ_PARCELAMENTO_DESPESA": "id_parcelamento_despesa",
    "DT_PAGTO_DESPESA": "data_pagamento_despesa",
    "VR_PAGTO_DESPESA": "valor_pagamento_despesa",
    "CD_FONTE_RECEITA": "codigo_fonte_receita",
    "DS_FONTE_RECEITA": "descricao_fonte_receita",
    "CD_ORIGEM_RECEITA": "codigo_origem_receita",
    "DS_ORIGEM_RECEITA": "descricao_origem_receita",
    "CD_NATUREZA_RECEITA": "codigo_natureza_receita",
    "DS_NATUREZA_RECEITA": "descricao_natureza_receita",
    "CD_ESPECIE_RECEITA": "codigo_especie_receita",
    "DS_ESPECIE_RECEITA": "descricao_especie_receita",
    "CD_CNAE_DOADOR": "codigo_cnae_doador",
    "DS_CNAE_DOADOR": "descricao_cnae_doador",
    "NR_CPF_CNPJ_DOADOR": "cpf_cnpj_doador",
    "NM_DOADOR": "nome_doador",
    "NM_DOADOR_RFB": "nome_doador_rfb",
    "CD_ESFERA_PARTIDARIA_DOADOR": "codigo_esfera_partidaria_doador",
    "DS_ESFERA_PARTIDARIA_DOADOR": "descricao_esfera_partidaria_doador",
    "SG_UF_DOADOR": "sigla_uf_doador",
    "CD_MUNICIPIO_DOADOR": "codigo_municipio_doador",
    "NM_MUNICIPIO_DOADOR": "nome_municipio_doador",
    "SQ_CANDIDATO_DOADOR": "id_candidato_doador",
    "NR_CANDIDATO_DOADOR": "numero_candidato_doador",
    "CD_CARGO_CANDIDATO_DOADOR": "codigo_cargo_doador",
    "DS_CARGO_CANDIDATO_DOADOR": "descricao_cargo_doador",
    "NR_PARTIDO_DOADOR": "numero_partido_doador",
    "SG_PARTIDO_DOADOR": "sigla_partido_doador",
    "NM_PARTIDO_DOADOR": "nome_partido_doador",
    "NR_RECIBO_DOACAO": "numero_recibo_doacao",
    "NR_DOCUMENTO_DOACAO": "numero_documento_doacao",
    "SQ_RECEITA": "id_receita",
    "DT_RECEITA": "data_receita",
    "DS_RECEITA": "descricao_receita",
    "VR_RECEITA": "valor_receita",
    "DS_NATUREZA_RECURSO_ESTIMAVEL": "natureza_recurso_estimavel",
    "NR_CPF_CNPJ_DOADOR_ORIGINARIO": "cpf_cnpj_doador_originario",
    "NM_DOADOR_ORIGINARIO": "nome_doador_originario",
    "NM_DOADOR_ORIGINARIO_RFB": "nome_doador_originario_rfb",
    "TP_DOADOR_ORIGINARIO": "tipo_doador_originario",
    "CD_CNAE_DOADOR_ORIGINARIO": "codigo_cnae_doador_originario",
    "DS_CNAE_DOADOR_ORIGINARIO": "descricao_cnae_doador_originario",

    # Locais de Votação e Eleitorado
    "CD_TIPO_SECAO_AGREGADA": "codigo_tipo_secao_agregada",
    "DS_TIPO_SECAO_AGREGADA": "descricao_tipo_secao_agregada",
    "NR_SECAO_PRINCIPAL": "numero_secao_principal",
    "NR_LOCAL_VOTACAO": "numero_local_votacao",
    "NM_LOCAL_VOTACAO": "nome_local_votacao",
    "CD_TIPO_LOCAL": "codigo_tipo_local",
    "DS_TIPO_LOCAL": "descricao_tipo_local",
    "DS_ENDERECO": "endereco",
    "NM_BAIRRO": "nome_bairro",
    "NR_CEP": "cep",
    "NR_TELEFONE_LOCAL": "telefone_local",
    "NR_LATITUDE": "latitude",
    "NR_LONGITUDE": "longitude",
    "CD_SITU_LOCAL_VOTACAO": "codigo_situacao_local_votacao",
    "DS_SITU_LOCAL_VOTACAO": "descricao_situacao_local_votacao",
    "CD_SITU_ZONA": "codigo_situacao_zona",
    "DS_SITU_ZONA": "descricao_situacao_zona",
    "CD_SITU_SECAO": "codigo_situacao_secao",
    "DS_SITU_SECAO": "descricao_situacao_secao",
    "CD_SITU_LOCALIDADE": "codigo_situacao_localidade",
    "DS_SITU_LOCALIDADE": "descricao_situacao_localidade",
    "CD_SITU_SECAO_ACESSIBILIDADE": "codigo_situacao_secao_acessibilidade",
    "DS_SITU_SECAO_ACESSIBILIDADE": "descricao_situacao_secao_acessibilidade",
    "QT_ELEITOR_SECAO": "quantidade_eleitores_secao",
    "QT_ELEITOR_ELEICAO_FEDERAL": "quantidade_eleitores_federal",
    "QT_ELEITOR_ELEICAO_ESTADUAL": "quantidade_eleitores_estadual",
    "QT_ELEITOR_ELEICAO_MUNICIPAL": "quantidade_eleitores_municipal",
    "NR_LOCAL_VOTACAO_ORIGINAL": "numero_local_votacao_original",
    "NM_LOCAL_VOTACAO_ORIGINAL": "nome_local_votacao_original",
    "DS_ENDERECO_LOCVT_ORIGINAL": "endereco_local_votacao_original",
    "CD_FAIXA_ETARIA": "codigo_faixa_etaria",
    "DS_FAIXA_ETARIA": "descricao_faixa_etaria",
    "CD_GRAU_ESCOLARIDADE": "codigo_grau_escolaridade",
    "DS_GRAU_ESCOLARIDADE": "descricao_grau_escolaridade",
    "CD_RACA_COR": "codigo_raca_cor",
    "DS_RACA_COR": "descricao_raca_cor",
    "CD_IDENTIDADE_GENERO": "codigo_identidade_genero",
    "DS_IDENTIDADE_GENERO": "descricao_identidade_genero",
    "CD_QUILOMBOLA": "codigo_quilombola",
    "DS_QUILOMBOLA": "descricao_quilombola",
    "CD_INTERPRETE_LIBRAS": "codigo_interprete_libras",
    "DS_INTERPRETE_LIBRAS": "descricao_interprete_libras",
    "QT_ELEITORES": "quantidade_eleitores",
    "QT_ELEITORES_BIOMETRIA": "quantidade_eleitores_biometria",
    "QT_ELEITORES_DEFICIENCIA": "quantidade_eleitores_deficiencia",
    "QT_ELEITORES_NOME_SOCIAL": "quantidade_eleitores_nome_social",
    "SQ_ELEITOR": "id_eleitor",
    "CD_MUN_SIT_BIOMETRICA": "codigo_situacao_biometrica",
    "DS_MUN_SIT_BIOMETRICA": "descricao_situacao_biometrica",
    "CD_TIPO_DEFICIENCIA": "codigo_tipo_deficiencia",
    "DS_TIPO_DEFICIENCIA": "descricao_tipo_deficiencia",
    "ST_ELEITOR_BIOMETRIA": "status_biometria_eleitor",
    "TP_OBRIGATORIEDADE_VOTO": "tipo_obrigatoriedade_voto",
    "QT_ELEITORES_PERFIL": "quantidade_eleitores_perfil",
    "QT_ELEITORES_INC_NM_SOCIAL": "quantidade_eleitores_nome_social",

    # Resultados e Votação
    "ST_VOTO_EM_TRANSITO": "voto_em_transito",
    "QT_VOTOS_NOMINAIS": "votos_nominais",
    "QT_VOTOS_NOMINAIS_VALIDOS": "votos_nominais_validos",
    "QT_VOTOS_LEGENDA_VALIDOS": "votos_legenda_validos",
    "QT_VOTOS_NOM_CONVR_LEG_VALIDOS": "votos_nominais_convertidos_legenda",
    "QT_TOTAL_VOTOS_LEG_VALIDOS": "total_votos_legenda_validos",
    "QT_VOTOS_LEGENDA_ANUL_SUBJUD": "votos_legenda_anulados_subjudice",
    "QT_VOTOS_NOMINAIS_ANUL_SUBJUD": "votos_nominais_anulados_subjudice",
    "QT_VOTOS_LEGENDA_ANULADOS": "votos_legenda_anulados",
    "QT_VOTOS_NOMINAIS_ANULADOS": "votos_nominais_anulados",

    # Censo IBGE
    "CD_REGIAO": "codigo_regiao",
    "NM_REGIAO": "nome_regiao",
    "CD_UF": "codigo_uf",
    "NM_UF": "nome_uf",
    "CD_DIST": "codigo_distrito",
    "NM_DIST": "nome_distrito",
    "CD_SUBDIST": "codigo_subdistrito",
    "NM_SUBDIST": "nome_subdistrito",
    "CD_BAIRRO": "codigo_bairro",
    "CD_RGINT": "codigo_regiao_intermediaria",
    "NM_RGINT": "nome_regiao_intermediaria",
    "CD_RGI": "codigo_regiao_imediata",
    "NM_RGI": "nome_regiao_imediata",
    "CD_CONCURB": "codigo_concentracao_urbana",
    "NM_CONCURB": "nome_concentracao_urbana",
    "AREA_KM2": "area_km2",
}


def traduzir_colunas_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Traduz siglas técnicas e códigos vXXXXX para nomes concisos em português leigo.

    Executa em tempo O(C) reescrevendo unicamente o índice de colunas do
    DataFrame, garantindo cópia zero de linhas e alocação nula de memória RAM.

    Args:
        df (pd.DataFrame): DataFrame com nomes de colunas originais.

    Returns:
        pd.DataFrame: DataFrame com colunas traduzidas e deduplicadas.
    """
    novas_colunas = []
    nomes_usados = set()

    for col in df.columns:
        col_str = str(col).strip().upper()

        if col_str in MAPA_TRADUCAO_COLUNAS:
            nome_traduzido = MAPA_TRADUCAO_COLUNAS[col_str]
        else:
            v_match = re.match(r"^V0*([1-7])$", col_str)
            if v_match:
                v_num = int(v_match.group(1))
                mapa_v = {
                    1: "total_pessoas",
                    2: "total_domicilios",
                    3: "total_domicilios_particulares",
                    4: "total_domicilios_coletivos",
                    5: "media_moradores_domicilios_particulares_ocupados",
                    6: "percentual_domicilios_particulares_ocupados_imputados",
                    7: "total_domicilios_particulares_ocupados",
                }
                nome_traduzido = mapa_v.get(v_num, col_str.lower())
            else:
                nome_traduzido = col_str.lower().replace(" ", "_")

        nome_final = nome_traduzido
        contador = 2
        while nome_final in nomes_usados:
            nome_final = f"{nome_traduzido}_{contador}"
            contador += 1

        nomes_usados.add(nome_final)
        novas_colunas.append(nome_final)

    df_traduzido = df.copy(deep=False)
    df_traduzido.columns = novas_colunas
    return df_traduzido


def sanitizar_id_serie(s: pd.Series) -> pd.Series:
    """Higieniza identificadores de forma vetorizada em C++ para Pandas Series.

    Args:
        s (pd.Series): Coluna de chave/ID de entrada.

    Returns:
        pd.Series: Coluna higienizada sem sufixos '.0' e sem espaços.
    """
    s_str = s.fillna("").astype(str).str.strip()
    tem_ponto_zero = s_str.str.endswith(".0")
    res = np.where(tem_ponto_zero, s_str.str[:-2], s_str)
    return pd.Series(res, index=s.index)


def sanitizar_texto_generico_serie(s: pd.Series) -> pd.Series:
    """Aplica trim e colapsa múltiplos espaços em C++ para Pandas Series.

    Args:
        s (pd.Series): Coluna textual de entrada.

    Returns:
        pd.Series: Coluna com texto normalizado.
    """
    return s.fillna("").astype(str).str.strip().str.replace(r"\s+", " ", regex=True)


def converter_moeda_brl_para_float_serie(s: pd.Series) -> pd.Series:
    """Converte valores monetários BRL para float64 de forma vetorizada em C++.

    Args:
        s (pd.Series): Coluna monetária bruta.

    Returns:
        pd.Series: Coluna numérica convertida para float64.
    """
    s_str = (
        s.fillna("0")
        .astype(str)
        .str.replace("R$", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.strip()
    )
    s_str = s_str.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s_str, errors="coerce").fillna(0.0).astype("float64")


def sanitizar_id(valor: object) -> str:
    """Sanitiza identificadores e chaves primarias/estrangeiras na carga ETL.
    
    Remove sufixos decimais (.0), espacos em branco e converte para string limpa.
    
    Args:
        valor: Valor bruto do campo de ID.
        
    Returns:
        str: Identificador higienizado e padronizado.
    """
    if pd.isna(valor) or valor is None:
        return ""
    
    texto = str(valor).strip()
    # Remove sufixo decimal gerado por inferencia de ponto flutuante (.0)
    texto = re.sub(r"\.0$", "", texto)
    
    valores_invalidos = {'0', '-1', '-4', '#nulo#', 'none', 'nan', 'null'}
    if texto.lower() in valores_invalidos:
        return ""
        
    return texto


def sanitizar_texto_generico(val: Any) -> str:
    """Aplica trim em texto escalar (compatibilidade unitária)."""
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip()
    return re.sub(r"\s+", " ", s)


def converter_moeda_brl_para_float(val: Any) -> float:
    """Converte valor monetário escalar para float (compatibilidade unitária)."""
    if pd.isna(val) or val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).replace("R$", "").replace(" ", "").strip()
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0