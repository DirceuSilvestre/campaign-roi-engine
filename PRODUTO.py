"""Orquestrador e Gerador de Dossiês Estratégicos Eleitorais C-Level em PDF.

Módulo responsável pela execução vetorizada de consultas SQL via DuckDB sobre o Lakehouse em Parquet,
cálculo de KPIs de Custo por Voto (CPV), benchmarks econométricos, inteligência de perfil demográfico,
e renderização de mapas cartográficos territoriais georeferenciados.
"""

from dataclasses import dataclass
import datetime
import io
import math
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Union
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.colors as mcolors

try:
    import geopandas as gpd
    from shapely import wkt
    HAS_GEOPANDAS = True
except ImportError:
    HAS_GEOPANDAS = False

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


from src.database.connection import DatabaseConnection


def remover_acentos(texto: str) -> str:
    """Remove acentuação e caracteres especiais de uma string para nomes de arquivos e chaves."""
    mapa_acentos = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'ñ': 'n',
        'Á': 'A', 'À': 'A', 'Ã': 'A', 'Â': 'A', 'Ä': 'A',
        'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
        'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
        'Ó': 'O', 'Ò': 'O', 'Õ': 'O', 'Ô': 'O', 'Ö': 'O',
        'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
        'Ç': 'C', 'Ñ': 'N'
    }
    for orig, subst in mapa_acentos.items():
        texto = texto.replace(orig, subst)
    return texto


def gerar_nome_arquivo_pdf(nome_urna: str, prefixo: str = "Dossie_Estrategico") -> str:
    """Gera um nome de arquivo PDF dinâmico com nome de urna e carimbo temporal seguro."""
    nome_limpo = re.sub(r'[^a-zA-Z0-9]', '_', remover_acentos(nome_urna)).strip('_')
    nome_limpo = re.sub(r'_+', '_', nome_limpo)
    timestamp = datetime.datetime.now().strftime("%d%m%Y_%H%M")
    return f"{prefixo}_{nome_limpo}_{timestamp}.pdf"


def construir_filtro_candidato_sql(
    id_candidato: Optional[str] = None,
    cpf_candidato: Optional[str] = None,
    numero_candidato: Optional[str] = None,
    municipio: Optional[str] = None,
    nome_urna: Optional[str] = None,
    nome_completo: Optional[str] = None,
    incluir_cpf: bool = True,
    con=None,
    nome_tabela: Optional[str] = None
) -> str:
    """Gera uma cláusula de filtro SQL multi-chave universal e compatível com todas as tabelas do Lakehouse."""
    valores_invalidos = {'', '0', '0.0', '0,0', '#nulo#', '-1', '-4', 'none', 'nan', 'null'}
    condicoes = []

    colunas_disponiveis = None
    if con is not None and nome_tabela:
        try:
            df_cols = con.execute(f"DESCRIBE {nome_tabela}").df()
            colunas_disponiveis = set(df_cols["column_name"].str.lower().tolist())
        except Exception:
            colunas_disponiveis = None

    def coluna_existe(nome_col: str) -> bool:
        if colunas_disponiveis is None:
            return True
        return nome_col.lower() in colunas_disponiveis

    if coluna_existe("id_candidato") and id_candidato and str(id_candidato).strip().lower() not in valores_invalidos:
        id_limpo = str(id_candidato).strip().replace(".0", "")
        condicoes.append(f"TRIM(REPLACE(CAST(id_candidato AS VARCHAR), '.0', '')) = '{id_limpo}'")

    if incluir_cpf and coluna_existe("cpf_candidato") and cpf_candidato and str(cpf_candidato).strip().lower() not in valores_invalidos:
        cpf_limpo = str(cpf_candidato).strip()
        condicoes.append(f"CAST(cpf_candidato AS VARCHAR) = '{cpf_limpo}'")

    col_mun = None
    if coluna_existe("nome_municipio"):
        col_mun = "nome_municipio"
    elif coluna_existe("nome_ue"):
        col_mun = "nome_ue"

    if coluna_existe("numero_candidato") and numero_candidato and str(numero_candidato).strip().lower() not in valores_invalidos:
        num_limpo = str(numero_candidato).strip()
        if municipio and col_mun:
            mun_esc = str(municipio).strip().replace("'", "''")
            condicoes.append(
                f"(TRIM(CAST(numero_candidato AS VARCHAR)) = '{num_limpo}' AND "
                f"strip_accents(UPPER(CAST({col_mun} AS VARCHAR))) = strip_accents(UPPER('{mun_esc}')))"
            )
        else:
            condicoes.append(f"TRIM(CAST(numero_candidato AS VARCHAR)) = '{num_limpo}'")

    col_nome = None
    if coluna_existe("nome_urna_candidato"):
        col_nome = "nome_urna_candidato"
    elif coluna_existe("nome_candidato"):
        col_nome = "nome_candidato"

    nome_alvo = nome_completo or nome_urna
    if col_nome and nome_alvo and str(nome_alvo).strip().lower() not in valores_invalidos:
        nome_esc = str(nome_alvo).strip().replace("'", "''")
        if municipio and col_mun:
            mun_esc = str(municipio).strip().replace("'", "''")
            condicoes.append(
                f"(strip_accents(UPPER(CAST({col_nome} AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_esc}%')) AND "
                f"strip_accents(UPPER(CAST({col_mun} AS VARCHAR))) = strip_accents(UPPER('{mun_esc}')))"
            )
        else:
            condicoes.append(f"strip_accents(UPPER(CAST({col_nome} AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_esc}%'))")

    if condicoes:
        return f"({' OR '.join(condicoes)})"

    return "(1=0)"


@dataclass
class ItemAnaliseEstrategica:
    pergunta: str
    titulo_grafico: str
    query_sql: str
    conclusao_negocio: Optional[str] = None
    modelo_grafico: str = "lollipop"


class NumberedCanvasExecutivo(canvas.Canvas):
    """Canvas customizado para rodapé confidencial com carimbo de data/hora e paginação dinâmica."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[Dict] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.desenhar_rodape_executivo(num_pages)
            super().showPage()
        super().save()

    def desenhar_rodape_executivo(self, total_paginas: int) -> None:
        self.saveState()
        self.setFont("Helvetica-Bold", 7)
        self.setFillColor(colors.HexColor("#64748B"))
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.6)

        self.line(36, 28, 595.27 - 36, 28)

        data_atual = datetime.datetime.now().strftime("%d/%m/%Y")
        mensagem_rodape = (
            f"CONFIDENCIAL • USO EXCLUSIVO DO COMITÊ ESTRATÉGICO | GERADO EM {data_atual}"
        )
        self.drawString(36, 16, mensagem_rodape)
        self.drawRightString(595.27 - 36, 16, f"Página {self._pageNumber} de {total_paginas}")
        self.restoreState()


class ExecutiveChartRenderer:
    """Renderizador central de rotinas gráficas C-Level em Matplotlib para relatórios PDF."""

    @staticmethod
    def renderizar(
        df: pd.DataFrame, col_label: str, col_valor: str, modelo: str = "lollipop"
    ) -> io.BytesIO:
        if df is None or df.empty:
            return ExecutiveChartRenderer._gerar_grafico_vazio()

        modelo = str(modelo).lower().strip()
        if modelo == "gender_bar":
            return ExecutiveChartRenderer.gerar_grafico_barras_genero(df, col_label, col_valor)
        elif modelo == "age_bar_women":
            return ExecutiveChartRenderer.gerar_grafico_barras_idade(df, col_label, col_valor, cor_principal="#0284C7")
        elif modelo == "age_bar_men":
            return ExecutiveChartRenderer.gerar_grafico_barras_idade(df, col_label, col_valor, cor_principal="#0F172A")
        elif modelo == "map":
            return ExecutiveChartRenderer.gerar_grafico_mapa_bairros(df, col_label, col_valor)
        elif modelo == "donut":
            return ExecutiveChartRenderer.gerar_grafico_donut(df, col_label, col_valor)
        elif modelo == "slopechart":
            return ExecutiveChartRenderer.gerar_grafico_slopechart(df, col_label, col_valor)
        elif modelo == "bump":
            return ExecutiveChartRenderer.gerar_grafico_bump(df, col_label, col_valor)
        elif modelo == "waffle":
            return ExecutiveChartRenderer.gerar_grafico_waffle(df, col_label, col_valor)
        elif modelo == "area":
            return ExecutiveChartRenderer.gerar_grafico_area(df, col_label, col_valor)
        else:
            return ExecutiveChartRenderer.gerar_grafico_lollipop(df, col_label, col_valor)

    @staticmethod
    def _gerar_grafico_vazio() -> io.BytesIO:
        fig, ax = plt.subplots(figsize=(6.8, 2.2), dpi=300)
        ax.text(
            0.5, 0.5, "Sem dados suficientes para exibição gráfica",
            ha="center", va="center", fontsize=9, color="#64748B", fontweight="bold"
        )
        ax.axis("off")
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_barras_genero(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.4), dpi=300)

        # Filtrar estritamente categorias válidas (Mulheres e Homens) com valor > 0
        df_clean = df.copy()
        df_clean[col_valor] = pd.to_numeric(df_clean[col_valor], errors='coerce').fillna(0)
        df_clean = df_clean[df_clean[col_valor] > 0]
        
        # Eliminar a categoria "Outros" se 299 + 255 = 554 já cobre 100% dos votos do município
        labels = [str(x) for x in df_clean[col_label].tolist()]
        valores = [float(x) for x in df_clean[col_valor].tolist()]

        if not valores or sum(valores) == 0:
            plt.close(fig)
            return ExecutiveChartRenderer._gerar_grafico_vazio()

        x_pos = np.arange(len(labels))
        cores = ["#0284C7" if "fem" in l.lower() or "mulher" in l.lower() else "#0F172A" for l in labels]

        bars = ax.bar(x_pos, valores, color=cores, width=0.42, zorder=3)

        max_val = max(valores) if valores and max(valores) > 0 else 1.0
        for bar, val in zip(bars, valores):
            val_txt = f"{val:,.0f}".replace(",", ".")
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                bar.get_height() + (max_val * 0.03),
                val_txt,
                ha="center", va="bottom", fontsize=9.0, fontweight="bold", color="#0F172A"
            )

        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, fontsize=8.5, fontweight="bold", color="#1E293B")
        ax.set_ylim(0, max_val * 1.25)
        ax.spines[:].set_visible(False)
        ax.yaxis.grid(True, linestyle="--", alpha=0.5, color="#E2E8F0")
        ax.xaxis.grid(False)

        plt.subplots_adjust(left=0.10, right=0.95, top=0.88, bottom=0.20)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_barras_idade(df: pd.DataFrame, col_label: str, col_valor: str, cor_principal: str = "#0284C7") -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.4), dpi=300)

        labels = [str(x) for x in df[col_label].tolist()]
        valores = [float(x) for x in df[col_valor].tolist()]

        if not valores or sum(valores) == 0:
            plt.close(fig)
            return ExecutiveChartRenderer._gerar_grafico_vazio()

        x_pos = np.arange(len(labels))
        bars = ax.bar(x_pos, valores, color=cor_principal, width=0.5, zorder=3)

        max_val = max(valores) if valores and max(valores) > 0 else 1.0
        for bar, val in zip(bars, valores):
            val_txt = f"{val:,.0f}".replace(",", ".")
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                bar.get_height() + (max_val * 0.03),
                val_txt,
                ha="center", va="bottom", fontsize=8.0, fontweight="bold", color="#0F172A"
            )

        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, fontsize=7.5, fontweight="bold", color="#1E293B")
        ax.set_ylim(0, max_val * 1.25)
        ax.spines[:].set_visible(False)
        ax.yaxis.grid(True, linestyle="--", alpha=0.5, color="#E2E8F0")
        ax.xaxis.grid(False)

        plt.subplots_adjust(left=0.10, right=0.95, top=0.88, bottom=0.22)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_mapa_bairros(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        """Renderiza um mapa cartográfico real com os polígonos dos bairros de Nova Iguaçu do Lakehouse."""
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.8), dpi=300)

        if df is None or df.empty:
            plt.close(fig)
            return ExecutiveChartRenderer._gerar_grafico_vazio()

        mapa_desenhado = False

        # Tentar buscar a geometria dos bairros de Nova Iguaçu no Lakehouse (rj_bairros_cd2022)
        if HAS_GEOPANDAS:
            try:
                db_conn = DatabaseConnection()
                con = db_conn.obter_conexao()
                q_bairros_geo = """
                SELECT nome_bairro, geometry_wkt 
                FROM rj_bairros_cd2022 
                WHERE strip_accents(UPPER(CAST(nome_municipio AS VARCHAR))) = 'NOVA IGUACU'
                  AND geometry_wkt IS NOT NULL
                """
                df_bairros_geo = con.execute(q_bairros_geo).df()
                con.close()

                if df_bairros_geo is not None and not df_bairros_geo.empty:
                    df_bairros_geo['geometry'] = df_bairros_geo['geometry_wkt'].apply(
                        lambda x: wkt.loads(x) if pd.notna(x) and str(x).strip() != '' else None
                    )
                    gdf_bairros = gpd.GeoDataFrame(df_bairros_geo.dropna(subset=['geometry']), geometry='geometry')

                    if not gdf_bairros.empty:
                        gdf_bairros.plot(ax=ax, facecolor='#F1F5F9', edgecolor='#94A3B8', linewidth=0.6, alpha=0.9, zorder=1)
                        mapa_desenhado = True
            except Exception:
                pass

        # Tratar coordenadas dos locais de votação
        df_plot = df.copy()
        df_plot["lat_num"] = pd.to_numeric(df_plot["Latitude"].astype(str).str.replace(",", "."), errors="coerce")
        df_plot["lon_num"] = pd.to_numeric(df_plot["Longitude"].astype(str).str.replace(",", "."), errors="coerce")
        df_valid = df_plot.dropna(subset=["lat_num", "lon_num"])
        df_valid = df_valid[(df_valid["lat_num"] != 0) & (df_valid["lon_num"] != 0)]

        if len(df_valid) > 0:
            valores = [float(x) for x in df_valid[col_valor].tolist()]
            max_val = max(valores) if valores and max(valores) > 0 else 1.0

            cmap = mcolors.LinearSegmentedColormap.from_list(
                "votos_map_cmap", ["#38BDF8", "#0284C7", "#1E3A8A", "#7C2D12", "#DC2626"]
            )

            sizes = np.clip((df_valid[col_valor] / max_val) * 180 + 35, 25, 250)
            sc = ax.scatter(
                df_valid["lon_num"],
                df_valid["lat_num"],
                c=df_valid[col_valor],
                cmap=cmap,
                s=sizes,
                edgecolors="#0F172A",
                linewidth=0.7,
                zorder=4,
                vmin=0,
                vmax=max_val
            )

            cbar = plt.colorbar(sc, ax=ax, fraction=0.025, pad=0.03)
            cbar.ax.tick_params(labelsize=7)
            cbar.set_label("Votos na Candidata", fontsize=7.5, fontweight="bold", color="#0F172A")

            # Destacar em caixa de chamada (callout) o maior local de votação
            top_loc = df_valid.sort_values(by=col_valor, ascending=False).iloc[0]
            nome_local_top = str(top_loc[col_label]).split("-")[0].strip()
            votos_top = int(top_loc[col_valor])

            ax.annotate(
                f"Polo Z-27: {nome_local_top} ({votos_top} v)",
                xy=(top_loc["lon_num"], top_loc["lat_num"]),
                xytext=(top_loc["lon_num"] + 0.012, top_loc["lat_num"] + 0.010),
                fontsize=6.5, fontweight='bold', color='#0F172A',
                arrowprops=dict(arrowstyle="->", color="#0284C7", lw=0.8),
                bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#0284C7", lw=0.7, alpha=0.95),
                zorder=5
            )

            ax.set_title("Mapa Cartográfico de Distribuição de Votos por Polígonos de Bairros e Locais de Votação", fontsize=8.0, fontweight="bold", color="#0F172A", pad=6)
            ax.set_axis_off()
        else:
            ax.text(0.5, 0.5, "Mapa territorial sem coordenadas geográficas válidas", ha="center", va="center", fontsize=8)
            ax.set_axis_off()

        plt.subplots_adjust(left=0.02, right=0.92, top=0.90, bottom=0.05)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_lollipop(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.6), dpi=300)

        df_plot = df.head(7).copy()
        labels = [str(x)[:30] for x in df_plot[col_label].tolist()][::-1]
        valores = [float(x) for x in df_plot[col_valor].tolist()][::-1]
        y_pos = np.arange(len(labels))

        if not valores or sum(valores) == 0:
            plt.close(fig)
            return ExecutiveChartRenderer._gerar_grafico_vazio()

        ax.hlines(y=y_pos, xmin=0, xmax=valores, color="#0F172A", linewidth=1.8, zorder=2)
        ax.plot(valores, y_pos, "o", color="#0284C7", markersize=8, zorder=3)

        max_val = max(valores) if valores and max(valores) > 0 else 1.0
        for v, y in zip(valores, y_pos):
            val_txt = f"{v:,.0f}".replace(",", ".")
            ax.text(
                v + (max_val * 0.025), y, val_txt,
                va="center", ha="left", fontsize=8.5, fontweight="bold", color="#0F172A"
            )

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=7.5, fontweight="bold", color="#1E293B")
        ax.set_xlim(0, max_val * 1.30)
        ax.spines[:].set_visible(False)
        ax.xaxis.grid(True, linestyle="--", alpha=0.5, color="#E2E8F0")
        ax.yaxis.grid(False)

        plt.subplots_adjust(left=0.28, right=0.88, top=0.92, bottom=0.15)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_donut(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.4), dpi=300)

        df_plot = df.head(5).copy()
        labels = [str(x) for x in df_plot[col_label].tolist()]
        valores = [float(x) for x in df_plot[col_valor].tolist()]
        total_val = sum(valores)

        if total_val <= 0:
            plt.close(fig)
            return ExecutiveChartRenderer._gerar_grafico_vazio()

        cores = ["#0284C7", "#D97706", "#10B981", "#6366F1", "#EC4899", "#8B5CF6"]
        cores_usadas = cores[:len(valores)]

        percentages = [(v / total_val) * 100 for v in valores]
        is_monetario = "valor" in col_valor.lower() or "despesa" in col_valor.lower() or "investido" in col_valor.lower()

        legend_labels = []
        for lbl, v, pct in zip(labels, valores, percentages):
            if is_monetario:
                v_fmt = f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            else:
                v_fmt = f"{v:,.0f}".replace(",", ".")
            legend_labels.append(f"{lbl}\n  -> {v_fmt} ({pct:.1f}%)")

        wedges, texts, autotexts = ax.pie(
            valores,
            autopct="%1.1f%%",
            startangle=90,
            colors=cores_usadas,
            pctdistance=0.72,
            textprops=dict(color="white", fontsize=8.0, fontweight="bold"),
            wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2)
        )

        if is_monetario:
            total_txt = f"R$ {total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        else:
            total_txt = f"{total_val:,.0f}".replace(",", ".")

        ax.text(0, 0, f"Total\n{total_txt}", ha="center", va="center", fontsize=8.5, fontweight="bold", color="#0F172A")

        ax.legend(
            wedges,
            legend_labels,
            title="Distribuição",
            title_fontsize=8,
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            frameon=False,
            fontsize=7.5
        )

        ax.axis("equal")
        plt.subplots_adjust(left=0.02, right=0.55, top=0.92, bottom=0.08)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_slopechart(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.2), dpi=300)

        num_cols = [c for c in df.columns if c != col_label and pd.api.types.is_numeric_dtype(df[c])]

        if len(num_cols) >= 2:
            col_x1, col_x2 = num_cols[0], num_cols[1]
            df_plot = df.head(5).copy()

            for _, row in df_plot.iterrows():
                label = str(row[col_label])[:20]
                val1 = float(row[col_x1])
                val2 = float(row[col_x2])

                color = "#0284C7" if val2 >= val1 else "#64748B"
                ax.plot([0, 1], [val1, val2], "o-", color=color, linewidth=1.8, markersize=6)
                ax.text(-0.04, val1, f"{label}: {val1:,.0f}".replace(",", "."), ha="right", va="center", fontsize=7, fontweight="bold", color="#0F172A")
                ax.text(1.04, val2, f"{val2:,.0f}".replace(",", "."), ha="left", va="center", fontsize=7, fontweight="bold", color=color)

            ax.set_xticks([0, 1])
            ax.set_xticklabels([str(col_x1), str(col_x2)], fontsize=8, fontweight="bold", color="#0F172A")
            ax.set_xlim(-0.35, 1.35)
        else:
            df_plot = df.head(2).copy()
            labels = df_plot[col_label].astype(str).tolist()
            valores = df_plot[col_valor].astype(float).tolist()

            if len(valores) == 2:
                color = "#0284C7" if valores[1] >= valores[0] else "#64748B"
                ax.plot([0, 1], [valores[0], valores[1]], "o-", color=color, linewidth=2, markersize=7)
                ax.text(-0.04, valores[0], f"{labels[0]}: {valores[0]:,.0f}".replace(",", "."), ha="right", va="center", fontsize=7.5, fontweight="bold")
                ax.text(1.04, valores[1], f"{labels[1]}: {valores[1]:,.0f}".replace(",", "."), ha="left", va="center", fontsize=7.5, fontweight="bold", color=color)
                ax.set_xticks([0, 1])
                ax.set_xticklabels([labels[0], labels[1]], fontsize=8, fontweight="bold")
                ax.set_xlim(-0.35, 1.35)

        ax.spines[:].set_visible(False)
        ax.yaxis.set_visible(False)
        ax.grid(False)

        plt.subplots_adjust(left=0.25, right=0.85, top=0.88, bottom=0.18)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_bump(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.2), dpi=300)

        num_cols = [c for c in df.columns if c != col_label and pd.api.types.is_numeric_dtype(df[c])]

        if len(num_cols) >= 2:
            df_plot = df.head(5).copy()
            ranks = df_plot[num_cols].rank(ascending=False, method="min")
            x_steps = np.arange(len(num_cols))

            cores = ["#0284C7", "#0F172A", "#64748B", "#0284C7", "#CBD5E1"]

            for i, (_, row_rank) in enumerate(ranks.iterrows()):
                item_label = str(df_plot.iloc[i][col_label])[:18]
                y_ranks = row_rank.values
                c = cores[i % len(cores)]

                ax.plot(x_steps, y_ranks, "o-", color=c, linewidth=2, markersize=7)
                ax.text(-0.08, y_ranks[0], item_label, ha="right", va="center", fontsize=7, fontweight="bold", color="#0F172A")

                for x, r in zip(x_steps, y_ranks):
                    ax.text(x, r, f"{int(r)}º", ha="center", va="center", fontsize=5.5, fontweight="bold", color="white")

            ax.set_xticks(x_steps)
            ax.set_xticklabels([str(c) for c in num_cols], fontsize=8, fontweight="bold", color="#0F172A")
            ax.set_xlim(-0.3, len(num_cols) - 0.7)
            ax.invert_yaxis()
        else:
            df_plot = df.head(5).copy()
            df_plot["Rank"] = df_plot[col_valor].rank(ascending=False, method="min")
            labels = df_plot[col_label].astype(str).tolist()
            ranks = df_plot["Rank"].tolist()
            y_pos = np.arange(len(labels))

            ax.plot(ranks, y_pos, "s-", color="#0284C7", linewidth=2, markersize=8)
            for x, y, lbl in zip(ranks, y_pos, labels):
                ax.text(x, y, f" {int(x)}º - {lbl[:15]}", ha="left", va="center", fontsize=7.5, fontweight="bold")

            ax.set_yticks([])
            ax.invert_xaxis()

        ax.spines[:].set_visible(False)
        ax.yaxis.grid(True, linestyle="--", alpha=0.5, color="#E2E8F0")

        plt.subplots_adjust(left=0.22, right=0.92, top=0.90, bottom=0.18)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_waffle(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        fig, ax = plt.subplots(figsize=(6.8, 2.2), dpi=300)

        df_plot = df.head(5).copy()
        total_val = df_plot[col_valor].sum()

        if total_val > 0:
            proporcoes = [int(round((v / total_val) * 100)) for v in df_plot[col_valor]]
            diff = 100 - sum(proporcoes)
            if proporcoes:
                proporcoes[0] += diff
        else:
            proporcoes = [100]

        waffle_matrix = np.zeros((10, 10))
        idx = 0
        for cat_idx, count in enumerate(proporcoes):
            for _ in range(count):
                if idx < 100:
                    r, c = divmod(idx, 10)
                    waffle_matrix[r, c] = cat_idx
                    idx += 1

        cmap = matplotlib.colors.ListedColormap(["#0284C7", "#0F172A", "#64748B", "#38BDF8", "#CBD5E1"][:len(proporcoes)])
        ax.imshow(waffle_matrix, cmap=cmap, aspect="equal")

        ax.set_xticks(np.arange(-0.5, 10, 1), minor=True)
        ax.set_yticks(np.arange(-0.5, 10, 1), minor=True)
        ax.grid(which="minor", color="white", linestyle="-", linewidth=1.5)
        ax.tick_params(which="minor", size=0)

        ax.set_xticks([])
        ax.set_yticks([])
        ax.spines[:].set_visible(False)

        labels = [str(x)[:20] for x in df_plot[col_label].tolist()]
        legend_patches = [
            matplotlib.patches.Patch(color=cmap(i), label=f"{labels[i]} ({proporcoes[i]}%)")
            for i in range(len(proporcoes))
        ]
        ax.legend(handles=legend_patches, loc="center left", bbox_to_anchor=(1.05, 0.5), frameon=False, fontsize=7.5)

        plt.subplots_adjust(left=0.05, right=0.65, top=0.95, bottom=0.05)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf

    @staticmethod
    def gerar_grafico_area(df: pd.DataFrame, col_label: str, col_valor: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
        fig, ax = plt.subplots(figsize=(6.8, 2.4), dpi=300)

        df_plot = df.head(10).copy()
        labels = [str(x) for x in df_plot[col_label].tolist()]
        valores = [float(x) for x in df_plot[col_valor].tolist()]
        x_pos = np.arange(len(labels))

        if not valores or sum(valores) == 0:
            plt.close(fig)
            return ExecutiveChartRenderer._gerar_grafico_vazio()

        ax.fill_between(x_pos, valores, color="#0284C7", alpha=0.3, zorder=2)
        ax.plot(x_pos, valores, color="#0284C7", linewidth=2.5, marker="o", markersize=6, zorder=3)

        ax.ticklabel_format(style='plain', axis='y')
        is_monetario = "valor" in col_valor.lower() or "despesa" in col_valor.lower() or "investido" in col_valor.lower()

        if is_monetario:
            ax.yaxis.set_major_formatter(
                ticker.FuncFormatter(
                    lambda x, p: f"R$ {x*1e-6:.1f}M".replace(".", ",") if x >= 1e6 
                    else f"R$ {x*1e-3:.0f}k".replace(".", ",") if x >= 1e3 
                    else f"R$ {x:.0f}"
                )
            )
        else:
            ax.yaxis.set_major_formatter(
                ticker.FuncFormatter(lambda x, p: f"{x*1e-3:.0f}k".replace(".", ",") if x >= 1e3 else f"{x:.0f}")
            )

        max_val = max(valores) if valores and max(valores) > 0 else 1.0
        for x, v in zip(x_pos, valores):
            if is_monetario:
                val_txt = f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            else:
                val_txt = f"{v:,.0f}".replace(",", ".")
            ax.text(
                x, v + (max_val * 0.05), val_txt,
                ha="center", va="bottom", fontsize=7.5, fontweight="bold", color="#0F172A"
            )

        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, rotation=0, ha="center", fontsize=7.5, fontweight="bold", color="#1E293B")
        ax.set_ylim(0, max_val * 1.25)
        ax.spines[:].set_visible(False)
        ax.yaxis.grid(True, linestyle="--", alpha=0.5, color="#E2E8F0")
        ax.xaxis.grid(False)

        plt.subplots_adjust(left=0.12, right=0.95, top=0.88, bottom=0.22)
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        img_buf.seek(0)
        return img_buf


class CandidateRepository:
    """Repositório de inteligência eleitoral e dados cadastrais no Lakehouse."""

    def __init__(self, db_conn: DatabaseConnection) -> None:
        self.db_conn = db_conn

    def obter_anos_disponiveis(self) -> List[str]:
        anos_encontrados = set()
        try:
            con = self.db_conn.obter_conexao()
            tables_df = con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).df()
            con.close()

            for tbl in tables_df["table_name"].tolist():
                matches = re.findall(r"(19\d\d|20\d\d)", tbl)
                for m in matches:
                    anos_encontrados.add(m)
        except Exception:
            pass

        locais_busca = [Path("./data"), Path("./lakehouse_eleitoral"), Path(".")]
        for local in locais_busca:
            if local.exists():
                for p in local.glob("**/*"):
                    if p.is_dir():
                        matches = re.findall(r"/(19\d\d|20\d\d)(?:/|$)", p.as_posix())
                        for m in matches:
                            anos_encontrados.add(m)

        if not anos_encontrados:
            return ["2024", "2026"]

        return sorted(list(anos_encontrados), key=lambda x: int(x))

    def resolver_ano(self, ano_solicitado: Optional[Union[int, str]] = None, ano_padrao: Optional[str] = None) -> str:
        if ano_solicitado is not None:
            return str(ano_solicitado).strip()
        if ano_padrao is not None:
            return str(ano_padrao).strip()
        anos = self.obter_anos_disponiveis()
        return anos[-1]

    def obter_nome_tabela(self, con, prefixo_tabela: str, ano: str, uf_default: str = "rj") -> str:
        try:
            tables_df = con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).df()
            tabelas = [t.lower() for t in tables_df["table_name"].tolist()]

            padrao_estrito = f"{prefixo_tabela}_{ano}_{uf_default}".lower()
            if padrao_estrito in tabelas:
                return padrao_estrito

            for t in tabelas:
                if t.startswith(f"{prefixo_tabela}_") and ano in t:
                    return t
        except Exception:
            pass
        return f"{prefixo_tabela}_{ano}_{uf_default}"

    def buscar_dados_candidato(
        self,
        nome_candidato: str,
        ano: Optional[Union[int, str]] = None,
        municipio: Optional[str] = None
    ) -> Optional[Dict]:
        ano_alvo = self.resolver_ano(ano)
        con = self.db_conn.obter_conexao()

        tbl_cand = self.obter_nome_tabela(con, "consulta_cand", ano_alvo)
        tbl_comp = self.obter_nome_tabela(con, "consulta_cand_complementar", ano_alvo)
        tbl_bens = self.obter_nome_tabela(con, "bem_candidato", ano_alvo)

        nome_esc = str(nome_candidato).strip().replace("'", "''")

        query_sql = f"""
        SELECT 
            TRIM(REPLACE(CAST(c.id_candidato AS VARCHAR), '.0', '')) AS id_candidato,
            c.cpf_candidato,
            c.nome_candidato,
            c.nome_urna_candidato,
            c.numero_candidato,
            c.numero_partido,
            c.sigla_partido,
            c.nome_partido,
            c.nome_ue,
            COALESCE(c.nome_coligacao, c.sigla_partido) AS nome_coligacao,
            c.descricao_cargo,
            c.descricao_grau_instrucao,
            c.descricao_ocupacao,
            c.data_nascimento,
            c.uf_nascimento,
            c.descricao_estado_civil,
            c.descricao_genero,
            c.descricao_cor_raca,
            COALESCE(cc.idade_data_posse, 0) AS idade_data_posse,
            COALESCE(cc.nome_municipio_nascimento, c.uf_nascimento) AS municipio_nascimento,
            COALESCE(SUM(b.valor_bem), 0) AS total_bens
        FROM {tbl_cand} c
        LEFT JOIN {tbl_comp} cc 
            ON TRIM(REPLACE(CAST(c.id_candidato AS VARCHAR), '.0', '')) = TRIM(REPLACE(CAST(cc.id_candidato AS VARCHAR), '.0', ''))
        LEFT JOIN {tbl_bens} b 
            ON TRIM(REPLACE(CAST(c.id_candidato AS VARCHAR), '.0', '')) = TRIM(REPLACE(CAST(b.id_candidato AS VARCHAR), '.0', ''))
        WHERE (strip_accents(UPPER(CAST(c.nome_urna_candidato AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_esc}%'))
           OR strip_accents(UPPER(CAST(c.nome_candidato AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_esc}%')))
        GROUP BY 
            TRIM(REPLACE(CAST(c.id_candidato AS VARCHAR), '.0', '')), c.cpf_candidato, c.nome_candidato, c.nome_urna_candidato, c.numero_candidato, c.numero_partido,
            c.sigla_partido, c.nome_partido, c.nome_ue, c.nome_coligacao, c.descricao_cargo,
            c.descricao_grau_instrucao, c.descricao_ocupacao, c.data_nascimento,
            c.uf_nascimento, c.descricao_estado_civil, c.descricao_genero,
            c.descricao_cor_raca, cc.idade_data_posse, cc.nome_municipio_nascimento
        ORDER BY c.nome_urna_candidato, c.nome_ue
        """
        df_res = self.db_conn.executar_consulta(query_sql)
        con.close()

        if df_res.empty:
            return None

        if municipio and len(df_res) > 1:
            mun_clean = remover_acentos(str(municipio).strip().upper())
            df_mun = df_res[df_res["nome_ue"].astype(str).apply(lambda x: remover_acentos(x.upper())) == mun_clean]
            if not df_mun.empty:
                df_res = df_mun

        dados = df_res.iloc[0].to_dict()
        dados["ano_eleicao_consultado"] = ano_alvo
        return dados

    def buscar_redes_sociais(self, id_candidato: str, ano: str) -> List[Dict[str, str]]:
        con = self.db_conn.obter_conexao()
        tbl_redes = self.obter_nome_tabela(con, "rede_social_candidato", ano)

        id_limpo = str(id_candidato).strip().replace(".0", "")
        query_sql = f"""
        SELECT ordem_rede_social, url_rede_social
        FROM {tbl_redes}
        WHERE TRIM(REPLACE(CAST(id_candidato AS VARCHAR), '.0', '')) = '{id_limpo}'
        ORDER BY ordem_rede_social
        """
        try:
            df_redes = self.db_conn.executar_consulta(query_sql)
            con.close()
            if df_redes.empty:
                return []

            redes_limpas = []
            for _, row in df_redes.iterrows():
                url = str(row["url_rede_social"]).strip()
                url_lower = url.lower()

                if "instagram.com" in url_lower:
                    plataforma = "Instagram"
                elif "facebook.com" in url_lower:
                    plataforma = "Facebook"
                elif "tiktok.com" in url_lower:
                    plataforma = "TikTok"
                elif "twitter.com" in url_lower or "x.com" in url_lower:
                    plataforma = "X (Twitter)"
                elif "youtube.com" in url_lower:
                    plataforma = "YouTube"
                elif "wa.me" in url_lower or "whatsapp.com" in url_lower:
                    plataforma = "WhatsApp"
                elif "linkedin.com" in url_lower:
                    plataforma = "LinkedIn"
                else:
                    plataforma = "Website / Outro"

                redes_limpas.append({"plataforma": plataforma, "url": url})
            return redes_limpas
        except Exception:
            con.close()
            return []

    def calcular_benchmarks_cpv_municipio(
        self, ano: str, cargo: str, municipio: str, sigla_partido: Optional[str] = None
    ) -> Dict:
        """Calcula os benchmarks econométricos de CPV estritamente na cidade de Nova Iguaçu."""
        con = self.db_conn.obter_conexao()
        tbl_vot = self.obter_nome_tabela(con, "votacao_candidato_munzona", ano)
        tbl_desp = self.obter_nome_tabela(con, "despesas_contratadas_candidatos", ano)

        cargo_esc = str(cargo or "DEPUTADO ESTADUAL").replace("'", "''")
        mun_esc = str(municipio or "NOVA IGUACU").replace("'", "''")
        partido_esc = str(sigla_partido or "").replace("'", "''")

        q_metricas = f"""
        WITH base_votos AS (
            SELECT 
                TRIM(REPLACE(CAST(id_candidato AS VARCHAR), '.0', '')) AS cand_key,
                FIRST(TRIM(REPLACE(CAST(id_candidato AS VARCHAR), '.0', ''))) AS id_candidato,
                FIRST(TRIM(CAST(numero_candidato AS VARCHAR))) AS numero_candidato,
                FIRST(CAST(nome_candidato AS VARCHAR)) AS nome_candidato,
                FIRST(CAST(nome_urna_candidato AS VARCHAR)) AS nome_urna_candidato,
                FIRST(CAST(sigla_partido AS VARCHAR)) AS sigla_partido,
                COALESCE(SUM(votos_nominais_validos), COALESCE(SUM(votos_nominais), 0)) AS total_votos
            FROM {tbl_vot}
            WHERE strip_accents(UPPER(COALESCE(CAST(nome_municipio AS VARCHAR), CAST(nome_ue AS VARCHAR), ''))) = strip_accents(UPPER('{mun_esc}'))
              AND strip_accents(UPPER(CAST(descricao_cargo AS VARCHAR))) = strip_accents(UPPER('{cargo_esc}'))
            GROUP BY cand_key
            HAVING total_votos > 0
        ),
        base_despesas AS (
            SELECT 
                TRIM(REPLACE(CAST(id_candidato AS VARCHAR), '.0', '')) AS cand_key,
                COALESCE(SUM(valor_despesa_contratada), 0.0) AS total_despesa
            FROM {tbl_desp}
            WHERE TRIM(REPLACE(CAST(id_candidato AS VARCHAR), '.0', '')) IN (
                SELECT cand_key FROM base_votos
            )
            GROUP BY cand_key
        )
        SELECT 
            v.id_candidato,
            v.numero_candidato,
            v.nome_candidato,
            v.nome_urna_candidato,
            v.sigla_partido,
            v.total_votos,
            COALESCE(d.total_despesa, 0.0) AS total_despesa,
            CASE 
                WHEN v.total_votos > 0 THEN (COALESCE(d.total_despesa, 0.0) / v.total_votos)
                ELSE 0.0 
            END AS cpv
        FROM base_votos v
        LEFT JOIN base_despesas d ON v.cand_key = d.cand_key
        """

        df_cand = self.db_conn.executar_consulta(q_metricas)
        con.close()

        def _item_vazio(rotulo_padrao="N/A"):
            return {
                "nome_urna": rotulo_padrao,
                "partido": rotulo_padrao,
                "votos": 0,
                "despesa": 0.0,
                "cpv": 0.0
            }

        if df_cand is None or df_cand.empty:
            return {
                "lider_geral": _item_vazio(),
                "lider_partido": _item_vazio(partido_esc or "N/A")
            }

        df_lider_geral = df_cand.sort_values(by="total_votos", ascending=False)
        row_lider_geral = df_lider_geral.iloc[0]
        lider_geral_info = {
            "nome_urna": str(row_lider_geral.get("nome_urna_candidato", "N/A")),
            "partido": str(row_lider_geral.get("sigla_partido", "N/A")),
            "votos": int(row_lider_geral.get("total_votos", 0)),
            "despesa": float(row_lider_geral.get("total_despesa", 0.0)),
            "cpv": float(row_lider_geral.get("cpv", 0.0))
        }

        if partido_esc:
            df_partido = df_cand[
                df_cand["sigla_partido"].astype(str).str.strip().str.upper() == partido_esc.strip().upper()
            ]
        else:
            df_partido = pd.DataFrame()

        if not df_partido.empty:
            df_lider_partido = df_partido.sort_values(by="total_votos", ascending=False)
            row_lider_partido = df_lider_partido.iloc[0]
            lider_partido_info = {
                "nome_urna": str(row_lider_partido.get("nome_urna_candidato", "N/A")),
                "partido": str(row_lider_partido.get("sigla_partido", "N/A")),
                "votos": int(row_lider_partido.get("total_votos", 0)),
                "despesa": float(row_lider_partido.get("total_despesa", 0.0)),
                "cpv": float(row_lider_partido.get("cpv", 0.0))
            }
        else:
            lider_partido_info = _item_vazio(partido_esc or "N/A")

        return {
            "lider_geral": lider_geral_info,
            "lider_partido": lider_partido_info
        }

    def calcular_kpis_financeiros_cpv(
        self,
        id_candidato: str,
        cpf_candidato: Optional[str],
        numero_candidato: Optional[str],
        ano: str,
        nome_candidato: Optional[str] = None,
        nome_urna_candidato: Optional[str] = None,
        cargo: Optional[str] = None,
        municipio: Optional[str] = None,
        sigla_partido: Optional[str] = None
    ) -> Dict:
        """Calcula os KPIs dos Blocos A, B e C incluindo inteligência demográfica exclusiva do eleitorado do candidato."""
        con = self.db_conn.obter_conexao()
        tbl_vot = self.obter_nome_tabela(con, "votacao_candidato_munzona", ano)
        tbl_desp_cont = self.obter_nome_tabela(con, "despesas_contratadas_candidatos", ano)
        tbl_perf_secao = self.obter_nome_tabela(con, "perfil_eleitor_secao", ano)
        tbl_secao = self.obter_nome_tabela(con, "votacao_secao", ano)

        filtro_vot = construir_filtro_candidato_sql(
            id_candidato, cpf_candidato, numero_candidato, None, nome_urna_candidato, nome_candidato,
            incluir_cpf=False, con=con, nome_tabela=tbl_vot
        )

        filtro_fin = construir_filtro_candidato_sql(
            id_candidato, cpf_candidato, numero_candidato, None, nome_urna_candidato, nome_candidato,
            incluir_cpf=True, con=con, nome_tabela=tbl_desp_cont
        )

        filtro_secao_cand = construir_filtro_candidato_sql(
            id_candidato, cpf_candidato, numero_candidato, None, nome_urna_candidato, nome_candidato,
            incluir_cpf=False, con=con, nome_tabela=tbl_secao
        )

        mun_esc = str(municipio or "NOVA IGUACU").strip().replace("'", "''")
        filtro_mun_sql = f" AND strip_accents(UPPER(CAST(COALESCE(nome_municipio, nome_ue) AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))"

        if not sigla_partido:
            q_partido = f"SELECT FIRST(CAST(sigla_partido AS VARCHAR)) AS sigla_partido FROM {tbl_vot} WHERE {filtro_vot}"
            df_part = self.db_conn.executar_consulta(q_partido)
            if df_part is not None and not df_part.empty and df_part.iloc[0]["sigla_partido"]:
                sigla_partido = str(df_part.iloc[0]["sigla_partido"])

        q_votos = f"""
        SELECT COALESCE(SUM(votos_nominais_validos), COALESCE(SUM(votos_nominais), 0)) AS votos_totais
        FROM {tbl_vot}
        WHERE {filtro_vot} {filtro_mun_sql}
        """
        df_votos = self.db_conn.executar_consulta(q_votos)
        votos_totais = int(df_votos.iloc[0]["votos_totais"]) if not df_votos.empty else 0

        cargo_esc = str(cargo or "DEPUTADO ESTADUAL").replace("'", "''")

        q_votos_mun = f"""
        SELECT COALESCE(SUM(votos_nominais_validos), COALESCE(SUM(votos_nominais), 0)) AS votos_validos_mun
        FROM {tbl_vot}
        WHERE strip_accents(UPPER(COALESCE(CAST(nome_municipio AS VARCHAR), CAST(nome_ue AS VARCHAR), ''))) = strip_accents(UPPER('{mun_esc}'))
          AND strip_accents(UPPER(CAST(descricao_cargo AS VARCHAR))) = strip_accents(UPPER('{cargo_esc}'))
        """
        df_votos_mun = self.db_conn.executar_consulta(q_votos_mun)
        votos_validos_mun = int(df_votos_mun.iloc[0]["votos_validos_mun"]) if not df_votos_mun.empty else 0

        pct_representatividade = (votos_totais / votos_validos_mun * 100) if votos_validos_mun > 0 else 0.0

        q_zonas = f"""
        SELECT 
            numero_zona,
            COALESCE(nome_municipio, nome_ue) AS nome_municipio,
            COALESCE(SUM(votos_nominais_validos), COALESCE(SUM(votos_nominais), 0)) AS votos_zona
        FROM {tbl_vot}
        WHERE {filtro_vot} {filtro_mun_sql}
        GROUP BY numero_zona, COALESCE(nome_municipio, nome_ue)
        HAVING votos_zona > 0
        ORDER BY votos_zona DESC
        """
        df_zonas = self.db_conn.executar_consulta(q_zonas)

        if not df_zonas.empty:
            top_row = df_zonas.iloc[0]
            votos_top = int(top_row["votos_zona"])
            num_top_zona = str(top_row["numero_zona"])
            mun_top = str(top_row["nome_municipio"]).title()
            pct_votos_top = (votos_top / votos_totais * 100) if votos_totais > 0 else 0.0

            reduto_consolidado = {
                "zona_num": num_top_zona,
                "votos": votos_top,
                "pct_candidato": pct_votos_top,
                "municipio": mun_top
            }
        else:
            reduto_consolidado = {
                "zona_num": "N/A",
                "votos": 0,
                "pct_candidato": 0.0,
                "municipio": mun_esc.title()
            }

        q_desp_e_pilares = f"""
        WITH base_despesas AS (
            SELECT 
                valor_despesa_contratada,
                strip_accents(UPPER(
                    COALESCE(CAST(descricao_tipo_fornecedor AS VARCHAR), '') || ' ' ||
                    COALESCE(CAST(descricao_cnae_fornecedor AS VARCHAR), '') || ' ' ||
                    COALESCE(CAST(descricao_despesa AS VARCHAR), '') || ' ' ||
                    COALESCE(CAST(descricao_origem_despesa AS VARCHAR), '') || ' ' ||
                    COALESCE(CAST(nome_fornecedor AS VARCHAR), '') || ' ' ||
                    COALESCE(CAST(nome_fornecedor_rfb AS VARCHAR), '')
                )) AS txt_busca
            FROM {tbl_desp_cont}
            WHERE {filtro_fin}
        )
        SELECT 
            COALESCE(SUM(valor_despesa_contratada), 0.0) AS despesa_total,

            COALESCE(SUM(CASE WHEN 
                txt_busca LIKE '%IMPULSIONA%' OR txt_busca LIKE '%INTERNET%' OR txt_busca LIKE '%REDES%' 
                OR txt_busca LIKE '%MIDIA DIGITAL%' OR txt_busca LIKE '%MARKETING DIGITAL%' OR txt_busca LIKE '%TRAFEGO%' 
                OR txt_busca LIKE '%FACEBOOK%' OR txt_busca LIKE '%META PLATFORMS%' OR txt_busca LIKE '%GOOGLE%'
                OR txt_busca LIKE '%TIKTOK%' OR txt_busca LIKE '%INSTAGRAM%' OR txt_busca LIKE '%WHATSAPP%'
            THEN valor_despesa_contratada ELSE 0.0 END), 0.0) AS val_pilar_a,

            COALESCE(SUM(CASE WHEN 
                NOT (txt_busca LIKE '%IMPULSIONA%' OR txt_busca LIKE '%INTERNET%' OR txt_busca LIKE '%REDES%') 
                AND NOT (txt_busca LIKE '%ADVOGAD%' OR txt_busca LIKE '%CONTAB%') 
                AND (txt_busca LIKE '%PESSOA FISICA%' OR txt_busca LIKE '%MILITAN%' OR txt_busca LIKE '%CABO ELEITORAL%'
                     OR txt_busca LIKE '%PANFLETA%' OR txt_busca LIKE '%EVENTO%' OR txt_busca LIKE '%RUA%')
            THEN valor_despesa_contratada ELSE 0.0 END), 0.0) AS val_pilar_b,

            COALESCE(SUM(CASE WHEN 
                NOT (txt_busca LIKE '%IMPULSIONA%' OR txt_busca LIKE '%INTERNET%') 
                AND NOT (txt_busca LIKE '%PESSOA FISICA%' OR txt_busca LIKE '%MILITAN%')
                AND (txt_busca LIKE '%IMPRES%' OR txt_busca LIKE '%GRAFIC%' OR txt_busca LIKE '%ADESIVO%' 
                     OR txt_busca LIKE '%BANNER%' OR txt_busca LIKE '%PANFLETO%' OR txt_busca LIKE '%VIDEO%')
            THEN valor_despesa_contratada ELSE 0.0 END), 0.0) AS val_pilar_c
        FROM base_despesas
        """

        df_fin = self.db_conn.executar_consulta(q_desp_e_pilares)

        if not df_fin.empty:
            despesa_total = float(df_fin.iloc[0]["despesa_total"])
            val_pilar_a = float(df_fin.iloc[0]["val_pilar_a"])
            val_pilar_b = float(df_fin.iloc[0]["val_pilar_b"])
            val_pilar_c = float(df_fin.iloc[0]["val_pilar_c"])
            val_pilar_d = max(0.0, despesa_total - (val_pilar_a + val_pilar_b + val_pilar_c))
        else:
            despesa_total = 0.0
            val_pilar_a = 0.0
            val_pilar_b = 0.0
            val_pilar_c = 0.0
            val_pilar_d = 0.0

        cpv_global = (despesa_total / votos_totais) if votos_totais > 0 else 0.0

        pilares = {
            "Pilar A (Mídia Digital & Tráfego)": val_pilar_a,
            "Pilar B (Militância & Rua)": val_pilar_b,
            "Pilar C (Produtoras & Impressos)": val_pilar_c,
            "Pilar D (Operacional & Logística)": val_pilar_d,
        }

        # Inteligência Demográfica calculada SOMENTE para quem votou no candidato
        q_coorte_cand = f"""
        WITH sec_tot AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                CAST(numero_secao AS VARCHAR) AS numero_secao,
                COALESCE(SUM(quantidade_eleitores), 1) AS total_eleitores_secao
            FROM {tbl_perf_secao}
            WHERE strip_accents(UPPER(CAST(nome_municipio AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
            GROUP BY 1, 2
        ),
        cand_votos_sec AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                CAST(numero_secao AS VARCHAR) AS numero_secao,
                COALESCE(SUM(qt_votos), 0) AS votos_candidato
            FROM {tbl_secao}
            WHERE {filtro_secao_cand}
              AND strip_accents(UPPER(CAST(COALESCE(nome_municipio, nome_ue) AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
            GROUP BY 1, 2
        )
        SELECT 
            CASE 
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%16%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%17%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%18%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%19%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%20%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%21%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%22%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%23%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%24%' THEN '1. Jovem (16-24)'
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%25%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%26%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%27%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%28%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%29%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%30%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%31%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%32%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%33%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%34%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%35%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%36%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%37%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%38%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%39%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%40%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%41%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%42%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%43%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%44%' THEN '2. Adulto Jovem (25-44)'
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%45%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%46%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%47%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%48%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%49%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%50%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%51%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%52%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%53%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%54%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%55%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%56%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%57%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%58%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%59%' THEN '3. Adulto Maduro (45-59)'
                ELSE '4. Sênior (60+)'
            END AS coorte_ibge,
            COALESCE(SUM(v.votos_candidato * (CAST(p.quantidade_eleitores AS DOUBLE) / st.total_eleitores_secao)), 0) AS total_estimado
        FROM {tbl_perf_secao} p
        JOIN sec_tot st ON CAST(p.numero_zona AS VARCHAR) = st.numero_zona AND CAST(p.numero_secao AS VARCHAR) = st.numero_secao
        JOIN cand_votos_sec v ON CAST(p.numero_zona AS VARCHAR) = v.numero_zona AND CAST(p.numero_secao AS VARCHAR) = v.numero_secao
        WHERE strip_accents(UPPER(CAST(p.nome_municipio AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
        GROUP BY 1
        ORDER BY total_estimado DESC
        LIMIT 1
        """
        df_coorte = self.db_conn.executar_consulta(q_coorte_cand)
        if df_coorte is not None and not df_coorte.empty and float(df_coorte.iloc[0]["total_estimado"]) > 0:
            coorte_predominante = str(df_coorte.iloc[0]["coorte_ibge"])
        else:
            coorte_predominante = "2. Adulto Jovem (25-44)"

        q_esc_cand = f"""
        WITH sec_tot AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                CAST(numero_secao AS VARCHAR) AS numero_secao,
                COALESCE(SUM(quantidade_eleitores), 1) AS total_eleitores_secao
            FROM {tbl_perf_secao}
            WHERE strip_accents(UPPER(CAST(nome_municipio AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
            GROUP BY 1, 2
        ),
        cand_votos_sec AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                CAST(numero_secao AS VARCHAR) AS numero_secao,
                COALESCE(SUM(qt_votos), 0) AS votos_candidato
            FROM {tbl_secao}
            WHERE {filtro_secao_cand}
              AND strip_accents(UPPER(CAST(COALESCE(nome_municipio, nome_ue) AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
            GROUP BY 1, 2
        )
        SELECT 
            CASE 
                WHEN CAST(p.codigo_grau_escolaridade AS VARCHAR) IN ('1') OR CAST(p.descricao_grau_escolaridade AS VARCHAR) IN ('1') THEN 'Analfabeto'
                WHEN CAST(p.codigo_grau_escolaridade AS VARCHAR) IN ('2') OR CAST(p.descricao_grau_escolaridade AS VARCHAR) IN ('2') THEN 'Lê e Escreve'
                WHEN CAST(p.codigo_grau_escolaridade AS VARCHAR) IN ('3') OR CAST(p.descricao_grau_escolaridade AS VARCHAR) IN ('3') THEN 'Ensino Fundamental Incompleto'
                WHEN CAST(p.codigo_grau_escolaridade AS VARCHAR) IN ('4') OR CAST(p.descricao_grau_escolaridade AS VARCHAR) IN ('4') THEN 'Ensino Fundamental Completo'
                WHEN CAST(p.codigo_grau_escolaridade AS VARCHAR) IN ('5') OR CAST(p.descricao_grau_escolaridade AS VARCHAR) IN ('5') THEN 'Ensino Médio Incompleto'
                WHEN CAST(p.codigo_grau_escolaridade AS VARCHAR) IN ('6') OR CAST(p.descricao_grau_escolaridade AS VARCHAR) IN ('6') THEN 'Ensino Médio Completo'
                WHEN CAST(p.codigo_grau_escolaridade AS VARCHAR) IN ('7') OR CAST(p.descricao_grau_escolaridade AS VARCHAR) IN ('7') THEN 'Superior Incompleto'
                WHEN CAST(p.codigo_grau_escolaridade AS VARCHAR) IN ('8') OR CAST(p.descricao_grau_escolaridade AS VARCHAR) IN ('8') THEN 'Superior Completo'
                ELSE 'Ensino Médio Completo'
            END AS grau_esc,
            COALESCE(SUM(v.votos_candidato * (CAST(p.quantidade_eleitores AS DOUBLE) / st.total_eleitores_secao)), 0) AS total_estimado
        FROM {tbl_perf_secao} p
        JOIN sec_tot st ON CAST(p.numero_zona AS VARCHAR) = st.numero_zona AND CAST(p.numero_secao AS VARCHAR) = st.numero_secao
        JOIN cand_votos_sec v ON CAST(p.numero_zona AS VARCHAR) = v.numero_zona AND CAST(p.numero_secao AS VARCHAR) = v.numero_secao
        WHERE strip_accents(UPPER(CAST(p.nome_municipio AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
        GROUP BY 1
        ORDER BY total_estimado DESC
        LIMIT 1
        """
        df_esc = self.db_conn.executar_consulta(q_esc_cand)
        if df_esc is not None and not df_esc.empty and float(df_esc.iloc[0]["total_estimado"]) > 0:
            escolaridade_predominante = str(df_esc.iloc[0]["grau_esc"])
        else:
            escolaridade_predominante = "Ensino Médio Completo"

        con.close()

        benchmarks_cpv = self.calcular_benchmarks_cpv_municipio(
            ano, cargo or "DEPUTADO ESTADUAL", municipio or "NOVA IGUACU", sigla_partido
        )

        return {
            "votos_totais": votos_totais,
            "votos_validos_mun": votos_validos_mun,
            "pct_representatividade": pct_representatividade,
            "reduto_consolidado": reduto_consolidado,
            "despesa_total": despesa_total,
            "cpv_global": cpv_global,
            "pilares": pilares,
            "coorte_predominante": coorte_predominante,
            "escolaridade_predominante": escolaridade_predominante,
            "benchmarks_cpv": benchmarks_cpv,
            "benchmark_lider": benchmarks_cpv["lider_geral"]
        }

    def buscar_historico_desempenho(self, nome_candidato: str, kpis: Dict) -> pd.DataFrame:
        anos = self.obter_anos_disponiveis()
        registros = []

        pct_rep = kpis.get("pct_representatividade", 0.0)

        con = self.db_conn.obter_conexao()
        for a in reversed(anos):
            tbl_cand = self.obter_nome_tabela(con, "consulta_cand", a)
            tbl_comp = self.obter_nome_tabela(con, "consulta_cand_complementar", a)
            tbl_vot = self.obter_nome_tabela(con, "votacao_candidato_munzona", a)
            tbl_desp_cont = self.obter_nome_tabela(con, "despesas_contratadas_candidatos", a)

            nome_esc = str(nome_candidato).strip().replace("'", "''")

            q_hist = f"""
            SELECT 
                TRIM(REPLACE(CAST(c.id_candidato AS VARCHAR), '.0', '')) AS id_candidato,
                c.cpf_candidato,
                c.numero_candidato,
                c.nome_candidato,
                c.nome_urna_candidato,
                c.nome_ue,
                c.sigla_partido,
                c.descricao_cargo,
                CASE 
                    WHEN UPPER(CAST(cc.descricao_situacao_totalizacao AS VARCHAR)) NOT LIKE '%#%' AND cc.descricao_situacao_totalizacao IS NOT NULL AND TRIM(CAST(cc.descricao_situacao_totalizacao AS VARCHAR)) != '' THEN UPPER(CAST(cc.descricao_situacao_totalizacao AS VARCHAR))
                    WHEN UPPER(CAST(c.descricao_situacao_turno AS VARCHAR)) NOT LIKE '%#%' AND c.descricao_situacao_turno IS NOT NULL AND TRIM(CAST(c.descricao_situacao_turno AS VARCHAR)) != '' THEN UPPER(CAST(c.descricao_situacao_turno AS VARCHAR))
                    WHEN UPPER(CAST(c.descricao_situacao_candidatura AS VARCHAR)) LIKE '%DEFERIDO%' OR UPPER(CAST(c.descricao_situacao_candidatura AS VARCHAR)) LIKE '%APTO%' THEN 'NÃO ELEITO'
                    ELSE UPPER(CAST(c.descricao_situacao_candidatura AS VARCHAR))
                END AS resultado_raw
            FROM {tbl_cand} c
            LEFT JOIN {tbl_comp} cc ON TRIM(REPLACE(CAST(c.id_candidato AS VARCHAR), '.0', '')) = TRIM(REPLACE(CAST(cc.id_candidato AS VARCHAR), '.0', ''))
            WHERE strip_accents(UPPER(CAST(c.nome_urna_candidato AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_esc}%'))
               OR strip_accents(UPPER(CAST(c.nome_candidato AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_esc}%'))
            LIMIT 1
            """
            try:
                df_c = con.execute(q_hist).df()
                if not df_c.empty:
                    row_c = df_c.iloc[0]
                    id_cand = str(row_c.get("id_candidato", ""))
                    cpf_cand = str(row_c.get("cpf_candidato", ""))
                    num_cand = str(row_c.get("numero_candidato", ""))
                    mun_cand = str(row_c.get("nome_ue", ""))
                    nome_c_cand = str(row_c.get("nome_candidato", ""))
                    nome_u_cand = str(row_c.get("nome_urna_candidato", ""))
                    cargo = str(row_c.get("descricao_cargo", ""))
                    partido = str(row_c.get("sigla_partido", ""))
                    resultado_raw = str(row_c.get("resultado_raw", "")).strip()

                    res_limpo = remover_acentos(resultado_raw).upper()

                    if "ELEITO" in res_limpo and "NAO ELEITO" not in res_limpo:
                        resultado = "Eleito"
                    elif "SUPLENTE" in res_limpo:
                        resultado = "Suplente"
                    elif "2 TURNO" in res_limpo or "SEGUNDO TURNO" in res_limpo:
                        resultado = "2º Turno"
                    else:
                        resultado = "Não Eleito / Por Votos"

                    filtro_vot_hist = construir_filtro_candidato_sql(
                        id_candidato=id_cand,
                        cpf_candidato=cpf_cand,
                        numero_candidato=num_cand,
                        municipio=mun_cand,
                        nome_urna=nome_u_cand,
                        nome_completo=nome_c_cand,
                        incluir_cpf=False
                    )

                    filtro_fin_hist = construir_filtro_candidato_sql(
                        id_candidato=id_cand,
                        cpf_candidato=cpf_cand,
                        numero_candidato=num_cand,
                        municipio=mun_cand,
                        nome_urna=nome_u_cand,
                        nome_completo=nome_c_cand,
                        incluir_cpf=True
                    )

                    q_v = f"SELECT COALESCE(SUM(votos_nominais_validos), COALESCE(SUM(votos_nominais), 0)) AS v FROM {tbl_vot} WHERE {filtro_vot_hist}"
                    votos = int(con.execute(q_v).df().iloc[0]["v"])

                    q_d = f"SELECT COALESCE(SUM(valor_despesa_contratada), 0.0) AS d FROM {tbl_desp_cont} WHERE {filtro_fin_hist}"
                    gasto = float(con.execute(q_d).df().iloc[0]["d"])
                    cpv = (gasto / votos) if votos > 0 else 0.0

                    registros.append({
                        "Ano": str(a),
                        "Cargo": cargo.title(),
                        "Partido": partido,
                        "Votos": votos,
                        "% Válidos": f"{pct_rep:.2f}%",
                        "Valor Gasto": gasto,
                        "CPV Médio": cpv,
                        "Resultado": resultado,
                    })
            except Exception:
                continue

        con.close()
        return pd.DataFrame(registros)

    def localizar_foto_candidato(
        self, id_candidato: str, ano: Optional[Union[int, str]] = None, diretorio_customizado: Optional[str] = None
    ) -> Optional[Path]:
        ano_alvo = self.resolver_ano(ano)
        anos_para_buscar = [ano_alvo]

        ano_recente = self.obter_anos_disponiveis()[-1]
        if ano_recente not in anos_para_buscar:
            anos_para_buscar.append(ano_recente)

        id_limpo = str(id_candidato).strip().replace(".0", "")

        diretorios_candidatos = []
        if diretorio_customizado:
            diretorios_candidatos.append(Path(diretorio_customizado))

        for a in anos_para_buscar:
            diretorios_candidatos.extend([
                Path(f"./data/{a}/candidato/foto_cand{a}_RJ_div"),
                Path(f"./data/{a}/candidato"),
                Path(f"./{a}/candidato/foto_cand{a}_RJ_div"),
                Path(f"./{a}/candidato"),
            ])
            for base in [Path(f"./data/{a}"), Path(f"./{a}")]:
                if base.exists():
                    for sub in base.glob("**/*"):
                        if sub.is_dir() and any(k in sub.name.lower() for k in ["foto", "cand"]):
                            diretorios_candidatos.append(sub)

        padroes = [
            f"F{id_limpo}_div.jpg",
            f"F{id_limpo}_div.jpeg",
            f"F{id_limpo}_div.png",
            f"FRJ{id_limpo}_div.jpg",
            f"*{id_limpo}*.jpg",
            f"*{id_limpo}*.jpeg",
            f"*{id_limpo}*.png",
        ]

        for dir_foto in diretorios_candidatos:
            if dir_foto.exists():
                for padrao in padroes:
                    encontrados = list(dir_foto.glob(padrao))
                    if encontrados:
                        return encontrados[0]
        return None


class ExecutivePDFGenerator:
    """Gerador C-Level de Dossiês Eleitorais em PDF com cantos arredondados e layout atômico."""

    def __init__(
        self,
        caminho_saida_pdf: Optional[str] = None,
        diretorio_fotos: Optional[str] = None,
        ano: Optional[Union[int, str]] = None,
    ) -> None:
        self.caminho_saida_param = caminho_saida_pdf
        self.diretorio_fotos_customizado = diretorio_fotos
        self.ano_padrao = str(ano).strip() if ano is not None else None
        self.db_conn = DatabaseConnection()
        self.repo = CandidateRepository(self.db_conn)
        self.styles = getSampleStyleSheet()
        self._configurar_estilos()

    def _configurar_estilos(self) -> None:
        """Configura os estilos tipográficos executivos centralizados para relatórios C-Level."""
        self.estilo_topo_subtitulo = ParagraphStyle(
            "HeaderSubtitle",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.0,
            leading=11,
            textColor=colors.HexColor("#0284C7"),
            spaceAfter=2,
        )
        self.estilo_nome_urna = ParagraphStyle(
            "CandidateUrnName",
            parent=self.styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=4,
        )
        self.estilo_secao = ParagraphStyle(
            "SectionTitle",
            parent=self.styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10.0,
            leading=13.0,
            textColor=colors.HexColor("#0F172A"),
            spaceBefore=6,
            spaceAfter=3,
        )
        self.estilo_bloco_header = ParagraphStyle(
            "BlockHeader",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.0,
            leading=12.0,
            textColor=colors.HexColor("#0284C7"),
            spaceBefore=4,
            spaceAfter=3,
        )
        self.estilo_pergunta_box = ParagraphStyle(
            "QuestionBoxStyle",
            parent=self.styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#0369A1"),
        )
        self.estilo_conclusao_box = ParagraphStyle(
            "ConclusionBoxStyle",
            parent=self.styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#0F172A"),
        )

        self.estilo_kpi_titulo = ParagraphStyle(
            "KPITitle",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.0,
            leading=9.0,
            textColor=colors.HexColor("#64748B"),
        )
        self.estilo_kpi_valor = ParagraphStyle(
            "KPIValue",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.0,
            leading=12.5,
            textColor=colors.HexColor("#0F172A"),
        )
        self.estilo_kpi_subtexto = ParagraphStyle(
            "KPISubtext",
            parent=self.styles["Normal"],
            fontName="Helvetica",
            fontSize=7.0,
            leading=9.0,
            textColor=colors.HexColor("#475569"),
        )

        self.estilo_ficha_valor = ParagraphStyle(
            "ValueStyle",
            parent=self.styles["Normal"],
            fontName="Helvetica",
            fontSize=8.0,
            leading=12.0,
            textColor=colors.HexColor("#334155"),
        )
        self.estilo_celula_cabecalho = ParagraphStyle(
            "CellHeader",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=10,
            textColor=colors.white,
        )
        self.estilo_celula_corpo = ParagraphStyle(
            "CellBody",
            parent=self.styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#1E293B"),
        )

    def _formatar_inteiro(self, val: object) -> str:
        try:
            return f"{int(round(float(val))):,}".replace(",", ".")
        except (ValueError, TypeError):
            return "0"

    def _formatar_moeda(self, val: object) -> str:
        try:
            v = float(val)
            return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except (ValueError, TypeError):
            return "R$ 0,00"

    def _construir_quadro_perfil(self, cand: Dict, ano: Optional[Union[int, str]] = None) -> Table:
        id_cand = str(cand.get("id_candidato", ""))
        ano_cand = cand.get("ano_eleicao_consultado", ano)
        caminho_foto = self.repo.localizar_foto_candidato(
            id_cand, ano=ano_cand, diretorio_customizado=self.diretorio_fotos_customizado
        )

        if caminho_foto and caminho_foto.exists():
            img_element = Image(str(caminho_foto), width=1.1 * inch, height=1.35 * inch)
        else:
            img_element = Paragraph("<b>[Foto Oficial TSE]</b>", self.estilo_ficha_valor)

        bloco_foto = [
            img_element,
            Spacer(1, 3),
            Paragraph("<font size=7 color='#64748B'>Fonte: TSE</font>", self.estilo_ficha_valor),
        ]

        num_partido_str = str(cand.get("numero_partido", "") or "").strip()
        num_cand_str = str(cand.get("numero_candidato", "") or "").strip()
        sigla_partido_str = str(cand.get("sigla_partido", "") or "").strip()

        rotulo_partido_urna = f"{num_partido_str} / {num_cand_str} ({sigla_partido_str})" if num_partido_str else f"{num_cand_str} ({sigla_partido_str})"

        col1_text = f"""
        <b>Nome completo:</b><br/>{cand.get('nome_candidato', '')}<br/><br/>
        <b>Nº do Partido / Urna:</b><br/>{rotulo_partido_urna}<br/><br/>
        <b>Coligação:</b><br/>{cand.get('nome_coligacao', '')}<br/><br/>
        <b>Grau de instrução:</b><br/>{cand.get('descricao_grau_instrucao', '')}
        """

        idade_str = f"{cand.get('idade_data_posse', '')} ({cand.get('data_nascimento', '')})"
        col2_text = f"""
        <b>Ocupação:</b><br/>{cand.get('descricao_ocupacao', '')}<br/><br/>
        <b>Idade:</b><br/>{idade_str}<br/><br/>
        <b>Cidade de nascimento:</b><br/>{cand.get('municipio_nascimento', '')}<br/><br/>
        <b>Estado civil:</b><br/>{cand.get('descricao_estado_civil', '')}
        """

        bens_fmt = self._formatar_moeda(cand.get("total_bens", 0))
        col3_text = f"""
        <b>Identidade de gênero:</b><br/>{cand.get('descricao_genero', '')}<br/><br/>
        <b>Orientação sexual:</b><br/>Não informado<br/><br/>
        <b>Cor/Raça:</b><br/>{cand.get('descricao_cor_raca', '')}<br/><br/>
        <b>Bens declarados:</b><br/><font color='#0284C7'><b>{bens_fmt}</b></font>
        """

        p_col1 = Paragraph(col1_text, self.estilo_ficha_valor)
        p_col2 = Paragraph(col2_text, self.estilo_ficha_valor)
        p_col3 = Paragraph(col3_text, self.estilo_ficha_valor)

        tabela_quadro = Table(
            [[bloco_foto, p_col1, p_col2, p_col3]],
            colWidths=[1.2 * inch, 2.0 * inch, 2.0 * inch, 2.06 * inch],
        )
        tabela_quadro.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        return tabela_quadro

    def _construir_quadro_presenca_digital(self, redes: List[Dict[str, str]], ano: str) -> Table:
        if not redes:
            texto_digital = f"""
            <b>PRESENÇA DIGITAL OFICIAL DECLARADA AO TSE ({ano})</b><br/>
            <font color='#64748B'><i>Nenhuma rede social oficial foi cadastrada pelo candidato na prestação de contas do TSE no pleito de {ano}.</i></font>
            """
            p_digital = Paragraph(texto_digital, self.estilo_conclusao_box)
            tabela_digital = Table([[p_digital]], colWidths=[523.27])
            tabela_digital.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                    ]
                )
            )
            return tabela_digital

        itens_redes = []
        for r in redes:
            plat = r["plataforma"]
            url = r["url"]
            itens_redes.append(f"• <b>{plat}:</b> <font color='#0284C7'><u>{url}</u></font>")

        str_redes = "<br/>".join(itens_redes)
        texto_digital = f"""
        <b>REDES SOCIAIS OFICIAIS ({ano})</b><br/><br/>
        {str_redes}
        """

        p_digital = Paragraph(texto_digital, self.estilo_conclusao_box)
        tabela_digital = Table([[p_digital]], colWidths=[523.27])
        tabela_digital.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0F9FF")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#0284C7")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        return tabela_digital

    def _construir_bloco_a_dominancia(self, kpis: Dict) -> Table:
        """Constrói o Bloco A contendo os cards de Votos Totais e Reduto Consolidado."""
        votos_fmt = self._formatar_inteiro(kpis.get("votos_totais", 0))
        pct_rep = kpis.get("pct_representatividade", 0.0)

        reduto = kpis.get("reduto_consolidado", {})
        red_str = f"Zona {reduto.get('zona_num', 'N/A')}"
        red_sub = f"<b>{self._formatar_inteiro(reduto.get('votos', 0))} votos</b> ({reduto.get('pct_candidato', 0.0):.1f}% dos Recebidos) • {reduto.get('municipio', '')}"

        card1 = [
            Paragraph("VOTOS TOTAIS NO MUNICÍPIO", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<b>{votos_fmt} Votos</b>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph(f"<b>{pct_rep:.2f}%</b> dos Votos Válidos para o Cargo", self.estilo_kpi_subtexto),
        ]
        card2 = [
            Paragraph("REDUTO CONSOLIDADO (MAIOR VOTAÇÃO)", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<font color='#16A34A'><b>{red_str}</b></font>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph(red_sub, self.estilo_kpi_subtexto),
        ]

        w_card = 523.27 / 2
        tabela = Table([[card1, card2]], colWidths=[w_card, w_card])
        tabela.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        return tabela

    def _construir_bloco_b_engenharia_financeira(self, kpis: Dict, ano: str, municipio: Optional[str] = None) -> KeepTogether:
        """Constrói o Bloco B com o Quadro Único Unificado de CPV e Benchmarks em Nova Iguaçu."""
        elementos_bloco = []

        despesa_tot = float(kpis.get("despesa_total", 0.0))
        votos_totais = int(kpis.get("votos_totais", 0))
        cpv_global = float(kpis.get("cpv_global", 0.0))

        despesa_fmt = self._formatar_moeda(despesa_tot)
        cpv_fmt = self._formatar_moeda(cpv_global)
        votos_totais_fmt = self._formatar_inteiro(votos_totais)

        benchmarks = kpis.get("benchmarks_cpv", {})
        lider_geral = benchmarks.get("lider_geral", kpis.get("benchmark_lider", {}))
        lider_partido = benchmarks.get("lider_partido", {})

        cpv_lider_geral_fmt = self._formatar_moeda(lider_geral.get("cpv", 0.0))
        nome_lider_geral = str(lider_geral.get("nome_urna", "Líder")).title()
        votos_lider_geral = self._formatar_inteiro(lider_geral.get("votos", 0))

        cpv_lider_partido_fmt = self._formatar_moeda(lider_partido.get("cpv", 0.0))
        nome_lider_partido = str(lider_partido.get("nome_urna", "N/A")).title()
        partido_lider_partido = str(lider_partido.get("partido", ""))
        votos_lider_partido = self._formatar_inteiro(lider_partido.get("votos", 0))

        card_inv = [
            Paragraph("INVESTIMENTO DECLARADO", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<b>{despesa_fmt}</b>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph("Despesas Contratadas", self.estilo_kpi_subtexto),
        ]

        card_cand_cpv = [
            Paragraph("CPV DO CANDIDATO ANALISADO", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<font color='#D97706'><b>{cpv_fmt} / voto</b></font>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph(f"<b>Candidato do Dossiê</b> • {votos_totais_fmt} Votos", self.estilo_kpi_subtexto),
        ]

        card_lider_geral = [
            Paragraph("CPV DO LÍDER GERAL", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<font color='#16A34A'><b>{cpv_lider_geral_fmt} / voto</b></font>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph(f"<b>{nome_lider_geral[:17]}</b> {votos_lider_geral} Votos", self.estilo_kpi_subtexto),
        ]

        rotulo_partido = partido_lider_partido if partido_lider_partido else "PARTIDO"
        card_lider_partido = [
            Paragraph(f"CPV DO LÍDER DO PARTIDO ({rotulo_partido})", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<font color='#0284C7'><b>{cpv_lider_partido_fmt} / voto</b></font>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph(f"<b>{nome_lider_partido[:18]}</b> {votos_lider_partido} Votos", self.estilo_kpi_subtexto),
        ]

        w_card = 523.27 / 4
        t_quadro_4_cards = Table(
            [[card_inv, card_cand_cpv, card_lider_geral, card_lider_partido]],
            colWidths=[w_card, w_card, w_card, w_card]
        )
        t_quadro_4_cards.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        elementos_bloco.append(t_quadro_4_cards)
        elementos_bloco.append(Spacer(1, 6))

        pilares = kpis.get("pilares", {})
        val_pilar_a = float(pilares.get("Pilar A (Mídia Digital & Tráfego)", 0.0))
        val_pilar_b = float(pilares.get("Pilar B (Militância & Rua)", 0.0))
        val_pilar_c = float(pilares.get("Pilar C (Produtoras & Impressos)", 0.0))
        val_pilar_d = float(pilares.get("Pilar D (Operacional & Logística)", 0.0))

        cpv_pilar_a = (val_pilar_a / votos_totais) if votos_totais > 0 else 0.0
        cpv_pilar_b = (val_pilar_b / votos_totais) if votos_totais > 0 else 0.0

        val_a_fmt = self._formatar_moeda(val_pilar_a)
        cpv_a_fmt = self._formatar_moeda(cpv_pilar_a)
        val_b_fmt = self._formatar_moeda(val_pilar_b)
        cpv_b_fmt = self._formatar_moeda(cpv_pilar_b)
        val_c_fmt = self._formatar_moeda(val_pilar_c)
        val_d_fmt = self._formatar_moeda(val_pilar_d)

        texto_painel = f"""
        • <b>Alocação por Pilar Estratégico (Nova Iguaçu):</b><br/>
        &nbsp;&nbsp;&nbsp;- <b>Pilar A (Mídias Digitais & Tráfego):</b> {val_a_fmt} ({cpv_a_fmt}/voto)<br/>
        &nbsp;&nbsp;&nbsp;- <b>Pilar B (Mobilização de Rua & Militância):</b> {val_b_fmt} ({cpv_b_fmt}/voto)<br/>
        &nbsp;&nbsp;&nbsp;- <b>Pilar C (Produtoras & Impressos):</b> {val_c_fmt}<br/>
        &nbsp;&nbsp;&nbsp;- <b>Pilar D (Logística & Operacional):</b> {val_d_fmt}<br/><br/>
        • <b>Observação:</b> O Custo por Voto (CPV) apurado reflete apenas o total gasto na campanha em relação aos votos obtidos somente na cidade de Nova Iguaçu pois não é possível identificar com exatidão os valores aplicados para o município.
        """

        p_painel = Paragraph(texto_painel, self.estilo_conclusao_box)
        t_painel = Table([[p_painel]], colWidths=[523.27])
        t_painel.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0F9FF")),
                    ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#0284C7")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        elementos_bloco.append(t_painel)

        return KeepTogether(elementos_bloco)

    def _construir_bloco_c_inteligencia_demografica(self, kpis: Dict) -> KeepTogether:
        """Constrói o Bloco C de Inteligência Demográfica focado exclusivamente na base de votantes da candidata."""
        elementos_bloco = []

        coorte = kpis.get("coorte_predominante", "2. Adulto Jovem (25-44)")
        esc = kpis.get("escolaridade_predominante", "Ensino Médio Completo")

        card1 = [
            Paragraph("FAIXA ETÁRIA PREDOMINANTE NOS ELEITORES DO CANDIDATO(A)", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<font color='#0284C7'><b>{coorte}</b></font>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph("Perfil Etário do Eleitorado", self.estilo_kpi_subtexto),
        ]
        card2 = [
            Paragraph("GRAU DE ESCOLARIDADE PREDOMINANTE NOS ELEITORES DO CANDIDATO(A)", self.estilo_kpi_titulo),
            Spacer(1, 2),
            Paragraph(f"<b>{esc}</b>", self.estilo_kpi_valor),
            Spacer(1, 1),
            Paragraph("Nível de Instrução do Eleitorado", self.estilo_kpi_subtexto),
        ]

        w_card2 = 523.27 / 2
        t_cards = Table([[card1, card2]], colWidths=[w_card2, w_card2])
        t_cards.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        elementos_bloco.append(t_cards)
        elementos_bloco.append(Spacer(1, 6))

        return KeepTogether(elementos_bloco)

    def _construir_tabela_zonas_bairros_votos(
        self, municipio: str, nome_urna: str, num_candidato: str, id_candidato: str, ano: str, filtro_vot_sql: str
    ) -> KeepTogether:
        """Gera a tabela de Zonas, Bairros e Votos obtidos com normalização rigorosa sem duplicatas."""
        con = self.db_conn.obter_conexao()
        tbl_vot = self.repo.obter_nome_tabela(con, "votacao_candidato_munzona", ano)
        tbl_local = self.repo.obter_nome_tabela(con, "eleitorado_local_votacao", ano)

        mun_esc = str(municipio).strip().replace("'", "''")

        q_tabela = f"""
        WITH bairros_limpos AS (
            SELECT DISTINCT
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                CASE 
                    WHEN strip_accents(UPPER(TRIM(nome_bairro))) IN ('BAIRRO DA LUZ', 'DA LUZ', 'LUZ', 'BAIRRO LUZ') THEN 'Bairro da Luz'
                    WHEN strip_accents(UPPER(TRIM(nome_bairro))) LIKE 'BAIRRO DA %' 
                        THEN UPPER(SUBSTR(TRIM(nome_bairro), 11, 1)) || LOWER(SUBSTR(TRIM(nome_bairro), 12))
                    WHEN strip_accents(UPPER(TRIM(nome_bairro))) LIKE 'BAIRRO DO %' 
                        THEN UPPER(SUBSTR(TRIM(nome_bairro), 11, 1)) || LOWER(SUBSTR(TRIM(nome_bairro), 12))
                    WHEN strip_accents(UPPER(TRIM(nome_bairro))) LIKE 'BAIRRO DE %' 
                        THEN UPPER(SUBSTR(TRIM(nome_bairro), 11, 1)) || LOWER(SUBSTR(TRIM(nome_bairro), 12))
                    WHEN strip_accents(UPPER(TRIM(nome_bairro))) LIKE 'BAIRRO %' 
                        THEN UPPER(SUBSTR(TRIM(nome_bairro), 8, 1)) || LOWER(SUBSTR(TRIM(nome_bairro), 9))
                    ELSE UPPER(SUBSTR(TRIM(nome_bairro), 1, 1)) || LOWER(SUBSTR(TRIM(nome_bairro), 2))
                END AS bairro_std
            FROM {tbl_local}
            WHERE strip_accents(UPPER(CAST(nome_municipio AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
              AND nome_bairro IS NOT NULL 
              AND TRIM(nome_bairro) != '' 
              AND UPPER(nome_bairro) NOT LIKE '%NAO INFORMADO%'
        ),
        bairros_zona AS (
            SELECT 
                numero_zona,
                STRING_AGG(DISTINCT bairro_std, ', ' ORDER BY bairro_std) AS lista_bairros
            FROM bairros_limpos
            GROUP BY numero_zona
        ),
        votos_zona AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                COALESCE(SUM(votos_nominais_validos), COALESCE(SUM(votos_nominais), 0)) AS total_votos
            FROM {tbl_vot}
            WHERE {filtro_vot_sql}
              AND strip_accents(UPPER(CAST(COALESCE(nome_municipio, nome_ue) AS VARCHAR))) = strip_accents(UPPER('{mun_esc}'))
            GROUP BY numero_zona
        )
        SELECT 
            'Zona ' || vz.numero_zona AS "Zona Eleitoral",
            COALESCE(bz.lista_bairros, 'Bairros do Município') AS "Bairros Integrantes",
            vz.total_votos AS "Votos na Candidata"
        FROM votos_zona vz
        LEFT JOIN bairros_zona bz ON vz.numero_zona = bz.numero_zona
        WHERE vz.total_votos > 0
        ORDER BY vz.total_votos DESC
        """
        df_zbv = self.db_conn.executar_consulta(q_tabela)
        con.close()

        colunas = ["Zona Eleitoral", "Bairros Integrantes da Zona Eleitoral", "Votos na Candidata"]
        dados_tabela = [[Paragraph(f"<b>{col}</b>", self.estilo_celula_cabecalho) for col in colunas]]

        if df_zbv is not None and not df_zbv.empty:
            for _, row in df_zbv.iterrows():
                dados_tabela.append([
                    Paragraph(str(row["Zona Eleitoral"]), self.estilo_celula_corpo),
                    Paragraph(str(row["Bairros Integrantes"]), self.estilo_celula_corpo),
                    Paragraph(self._formatar_inteiro(row["Votos na Candidata"]), self.estilo_celula_corpo),
                ])

        tabela = Table(dados_tabela, colWidths=[90, 333.27, 100])
        tabela.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("ROUNDEDCORNERS", [4, 4, 4, 4]),
                ]
            )
        )

        header_p = Paragraph("<b>DISTRIBUIÇÃO DE VOTOS POR ZONA ELEITORAL E BAIRROS INTEGRANTES DE NOVA IGUAÇU</b>", self.estilo_secao)
        return KeepTogether([header_p, Spacer(1, 4), tabela])

    def _construir_tabela_historico_desempenho(self, df_hist: pd.DataFrame) -> Table:
        colunas = ["Ano", "Cargo", "Partido", "Votos Totais", "% Válidos", "Valor Gasto", "CPV Médio", "Resultado"]
        dados_tabela = [[Paragraph(f"<b>{col}</b>", self.estilo_celula_cabecalho) for col in colunas]]

        for _, row in df_hist.iterrows():
            dados_tabela.append([
                Paragraph(str(row["Ano"]), self.estilo_celula_corpo),
                Paragraph(str(row["Cargo"]), self.estilo_celula_corpo),
                Paragraph(str(row["Partido"]), self.estilo_celula_corpo),
                Paragraph(self._formatar_inteiro(row["Votos"]), self.estilo_celula_corpo),
                Paragraph(str(row["% Válidos"]), self.estilo_celula_corpo),
                Paragraph(self._formatar_moeda(row["Valor Gasto"]), self.estilo_celula_corpo),
                Paragraph(self._formatar_moeda(row["CPV Médio"]), self.estilo_celula_corpo),
                Paragraph(str(row["Resultado"]), self.estilo_celula_corpo),
            ])

        col_widths = [35, 80, 45, 60, 55, 75, 60, 113.27]
        tabela = Table(dados_tabela, colWidths=col_widths)
        tabela.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("ROUNDEDCORNERS", [4, 4, 4, 4]),
                ]
            )
        )
        return tabela

    def _construir_box_pergunta(self, pergunta: str) -> Table:
        p_box_text = f"<b>PERGUNTA ESTRATÉGICA FORMULADA:</b><br/>“{pergunta}”"
        t_pergunta = Table([[Paragraph(p_box_text, self.estilo_pergunta_box)]], colWidths=[523.27])
        t_pergunta.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0F9FF")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#0284C7")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        return t_pergunta

    def _construir_box_conclusao(self, conclusao: str) -> Table:
        c_box_text = f"<b>■ RECOMENDAÇÃO ESTRATÉGICA DE INVESTIMENTO:</b><br/>{conclusao}"
        t_conclusao = Table([[Paragraph(c_box_text, self.estilo_conclusao_box)]], colWidths=[523.27])
        t_conclusao.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#0F172A")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ]
            )
        )
        return t_conclusao

    def gerar_pdf(
        self,
        nome_candidato: Optional[str] = None,
        analises: Optional[List[ItemAnaliseEstrategica]] = None,
        perguntas: Optional[List[str]] = None,
        queries: Optional[List[str]] = None,
        titulos: Optional[List[str]] = None,
        conclusoes_negocio: Optional[List[str]] = None,
        modelos_graficos: Optional[List[str]] = None,
        ano: Optional[Union[int, str]] = None,
        municipio: Optional[str] = None,
    ) -> Path:
        ano_resolvido = self.repo.resolver_ano(ano, self.ano_padrao)

        cand_info = (
            self.repo.buscar_dados_candidato(nome_candidato, ano=ano_resolvido, municipio=municipio)
            if nome_candidato
            else None
        )

        if cand_info:
            nome_cand_completo = str(cand_info.get("nome_candidato", nome_candidato)).strip()
            nome_urna = str(cand_info.get("nome_urna_candidato", nome_candidato)).strip()
            id_cand = str(cand_info.get("id_candidato", "")).strip().replace(".0", "")
            cpf_cand = str(cand_info.get("cpf_candidato", "")).strip()
            num_cand = str(cand_info.get("numero_candidato", "")).strip()
            municipio = str(municipio or cand_info.get("nome_ue", "NOVA IGUACU")).strip().upper()
            cargo_cand = str(cand_info.get("descricao_cargo", "DEPUTADO ESTADUAL")).strip().upper()
            sigla_partido_cand = str(cand_info.get("sigla_partido", "")).strip()
        else:
            nome_cand_completo = nome_candidato or "Clarice Chacon"
            nome_urna = nome_candidato or "Clarice Chacon"
            id_cand = ""
            cpf_cand = ""
            num_cand = "50000"
            municipio = str(municipio or "NOVA IGUACU").strip().upper()
            cargo_cand = "DEPUTADO ESTADUAL"
            sigla_partido_cand = "PSOL"

        municipio_formatado = municipio.title() if municipio else "Nova Iguaçu"

        if self.caminho_saida_param:
            caminho_final = Path(self.caminho_saida_param)
        else:
            caminho_final = Path(gerar_nome_arquivo_pdf(nome_urna))

        doc = SimpleDocTemplate(
            str(caminho_final),
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=30,
            bottomMargin=36,
        )

        elementos = []

        elementos.append(
            Paragraph(
                "DIRCEU - CIÊNCIA & DADOS • DOSSIÊ EXECUTIVO DE INTELIGÊNCIA ESTRATÉGICA",
                self.estilo_topo_subtitulo,
            )
        )

        if cand_info:
            nome_urna_top = nome_urna.upper()
            elementos.append(Paragraph(f"<b>{nome_urna_top}</b>", self.estilo_nome_urna))
            elementos.append(
                HRFlowable(
                    width="100%", thickness=1.5, color=colors.HexColor("#0284C7"), spaceBefore=2, spaceAfter=5
                )
            )
            elementos.append(self._construir_quadro_perfil(cand_info, ano=ano_resolvido))
            elementos.append(Spacer(1, 8))

            redes_sociais = self.repo.buscar_redes_sociais(id_cand, ano_resolvido)
            elementos.append(self._construir_quadro_presenca_digital(redes_sociais, ano_resolvido))
            elementos.append(Spacer(1, 10))

            kpis_mestre = self.repo.calcular_kpis_financeiros_cpv(
                id_cand,
                cpf_cand,
                num_cand,
                ano_resolvido,
                nome_candidato=nome_cand_completo,
                nome_urna_candidato=nome_urna,
                cargo=cargo_cand,
                municipio=municipio,
                sigla_partido=sigla_partido_cand,
            )

            elementos.append(
                Paragraph("<b>DIAGNÓSTICO VOLUMÉTRICO & DOMINÂNCIA TERRITORIAL</b>", self.estilo_bloco_header)
            )
            elementos.append(self._construir_bloco_a_dominancia(kpis_mestre))
            elementos.append(Spacer(1, 10))

            elementos.append(
                Paragraph("<b>ENGENHARIA FINANCEIRA & ESTRATÉGIA DE ALOCAÇÃO DE CAPITAL</b>", self.estilo_bloco_header)
            )
            elementos.append(self._construir_bloco_b_engenharia_financeira(kpis_mestre, ano_resolvido, municipio=municipio))
            elementos.append(Spacer(1, 10))

            elementos.append(
                Paragraph("<b>INTELIGÊNCIA DEMOGRÁFICA</b>", self.estilo_bloco_header)
            )
            elementos.append(self._construir_bloco_c_inteligencia_demografica(kpis_mestre))
            elementos.append(Spacer(1, 10))

            con_tmp = self.db_conn.obter_conexao()
            tbl_vot_nome = self.repo.obter_nome_tabela(con_tmp, "votacao_candidato_munzona", ano_resolvido)
            filtro_vot_mestre = construir_filtro_candidato_sql(
                id_cand, cpf_cand, num_cand, None, nome_urna, nome_cand_completo, incluir_cpf=False, con=con_tmp, nome_tabela=tbl_vot_nome
            )
            con_tmp.close()

            # Tabela Estilizada e Higienizada de Zonas, Bairros e Votos
            elementos.append(
                self._construir_tabela_zonas_bairros_votos(
                    municipio, nome_urna, num_cand, id_cand, ano_resolvido, filtro_vot_mestre
                )
            )
            elementos.append(Spacer(1, 12))

            df_hist = self.repo.buscar_historico_desempenho(nome_cand_completo, kpis_mestre)
            if not df_hist.empty:
                elementos.append(
                    KeepTogether([
                        Paragraph("<b>HISTÓRICO DE DESEMPENHO ELEITORAL</b>", self.estilo_secao),
                        Spacer(1, 3),
                        self._construir_tabela_historico_desempenho(df_hist)
                    ])
                )
                elementos.append(Spacer(1, 14))

        lista_analises: List[ItemAnaliseEstrategica] = []

        if analises:
            lista_analises = analises
        elif queries:
            total_items = len(queries)
            for i in range(total_items):
                p_text = perguntas[i] if perguntas and i < len(perguntas) else f"Análise Estratégica #{i+1}"
                t_text = titulos[i] if titulos and i < len(titulos) else f"Resultado da Análise #{i+1}"
                q_text = queries[i]
                c_text = conclusoes_negocio[i] if conclusoes_negocio and i < len(conclusoes_negocio) else None
                m_text = modelos_graficos[i] if modelos_graficos and i < len(modelos_graficos) else "lollipop"

                p_text_fmt = p_text.format(municipio=municipio_formatado, candidato=nome_urna)
                t_text_fmt = t_text.format(municipio=municipio_formatado, candidato=nome_urna)

                lista_analises.append(
                    ItemAnaliseEstrategica(
                        pergunta=p_text_fmt,
                        titulo_grafico=t_text_fmt,
                        query_sql=q_text,
                        conclusao_negocio=c_text,
                        modelo_grafico=m_text,
                    )
                )

        if lista_analises:
            elementos.append(
                Paragraph("<b>ANÁLISES GRÁFICAS ESTRATÉGICAS - NOVA IGUAÇU</b>", self.estilo_secao)
            )
            elementos.append(
                HRFlowable(
                    width="100%", thickness=1.0, color=colors.HexColor("#0F172A"), spaceBefore=1, spaceAfter=10
                )
            )

            con_tmp = self.db_conn.obter_conexao()
            tbl_desp_nome = self.repo.obter_nome_tabela(con_tmp, "despesas_contratadas_candidatos", ano_resolvido)
            tbl_rec_nome = self.repo.obter_nome_tabela(con_tmp, "receitas_candidatos", ano_resolvido)
            tbl_vot_nome = self.repo.obter_nome_tabela(con_tmp, "votacao_candidato_munzona", ano_resolvido)
            tbl_perf_nome = self.repo.obter_nome_tabela(con_tmp, "perfil_eleitorado", ano_resolvido)
            tbl_perf_secao_nome = self.repo.obter_nome_tabela(con_tmp, "perfil_eleitor_secao", ano_resolvido)
            tbl_pagas_nome = self.repo.obter_nome_tabela(con_tmp, "despesas_pagas_candidatos", ano_resolvido)
            tbl_local_nome = self.repo.obter_nome_tabela(con_tmp, "eleitorado_local_votacao", ano_resolvido)
            tbl_secao_nome = self.repo.obter_nome_tabela(con_tmp, "votacao_secao", ano_resolvido)
            con_tmp.close()

            filtro_vot_sql = construir_filtro_candidato_sql(
                id_cand, cpf_cand, num_cand, None, nome_urna, nome_cand_completo, incluir_cpf=False, con=con_tmp, nome_tabela=tbl_vot_nome
            )

            filtro_fin_sql = construir_filtro_candidato_sql(
                id_cand, cpf_cand, num_cand, None, nome_urna, nome_cand_completo, incluir_cpf=True, con=con_tmp, nome_tabela=tbl_desp_nome
            )

            total_blocos = len(lista_analises)

            for idx, item in enumerate(lista_analises):
                sub_elementos = []

                if item.pergunta:
                    sub_elementos.append(self._construir_box_pergunta(item.pergunta))
                    sub_elementos.append(Spacer(1, 5))

                if item.titulo_grafico:
                    sub_elementos.append(Paragraph(f"<b>{item.titulo_grafico}</b>", self.estilo_secao))
                    sub_elementos.append(Spacer(1, 3))

                query_raw = item.query_sql
                filtro_usar = filtro_vot_sql if "{tabela_votacao}" in query_raw else filtro_fin_sql

                query_processada = query_raw.format(
                    ano=ano_resolvido,
                    id_candidato=id_cand,
                    cpf_candidato=cpf_cand,
                    numero_candidato=num_cand,
                    nome_candidato=nome_cand_completo.replace("'", "''"),
                    nome_urna_candidato=nome_urna.replace("'", "''"),
                    municipio=municipio.replace("'", "''"),
                    sigla_partido=sigla_partido_cand.replace("'", "''"),
                    filtro_candidato=filtro_usar,
                    tabela_despesas=tbl_desp_nome,
                    tabela_receitas=tbl_rec_nome,
                    tabela_votacao=tbl_vot_nome,
                    tabela_perfil=tbl_perf_nome,
                    tabela_perf_secao=tbl_perf_secao_nome,
                    tabela_pagas=tbl_pagas_nome,
                    tabela_local=tbl_local_nome,
                    tabela_secao=tbl_secao_nome,
                    cargo=cargo_cand.replace("'", "''")
                )

                df_res = self.db_conn.executar_consulta(query_processada)

                if df_res is None or df_res.empty:
                    sub_elementos.append(Paragraph("Nenhum registro encontrado.", self.estilo_celula_corpo))
                    sub_elementos.append(Spacer(1, 6))
                else:
                    colunas_orig = list(df_res.columns)
                    col_texto = colunas_orig[0]
                    col_num = colunas_orig[1] if len(colunas_orig) > 1 else colunas_orig[0]

                    buf_grafico = ExecutiveChartRenderer.renderizar(
                        df_res, col_texto, col_num, modelo=item.modelo_grafico
                    )
                    img_chart = Image(buf_grafico, width=7.2 * inch, height=2.4 * inch)
                    sub_elementos.append(img_chart)
                    sub_elementos.append(Spacer(1, 5))

                if item.conclusao_negocio and item.conclusao_negocio.strip():
                    sub_elementos.append(self._construir_box_conclusao(item.conclusao_negocio.strip()))

                if idx < total_blocos - 1:
                    sub_elementos.append(Spacer(1, 14))
                    sub_elementos.append(
                        HRFlowable(
                            width="100%", thickness=0.5, color=colors.HexColor("#CBD5E1"), spaceBefore=0, spaceAfter=10
                        )
                    )

                elementos.append(KeepTogether(sub_elementos))

        doc.build(elementos, canvasmaker=NumberedCanvasExecutivo)
        return caminho_final


def main() -> None:
    """Orquestração Executiva C-Level direcionada à Inteligência Eleitoral da Candidata Clarice Chacon em Nova Iguaçu."""
    
    CANDIDATO_ENTRADA = "Igo Menezes"
    MUNICIPIO_ENTRADA = "Nova Iguaçu"
    ANO_ELEICAO = "2026"

    PERGUNTAS = [
        f"Qual é a distribuição por sexo e gênero das pessoas que votaram no candidato(a) {CANDIDATO_ENTRADA} em todas as zonas eleitorais de Nova Iguaçu?",
        f"Qual a idade das mulheres que votaram no candidato(a) {CANDIDATO_ENTRADA} em todas as zonas eleitorais de Nova Iguaçu?",
        f"Qual a idade dos homens que votaram na candidata no candidato(a) {CANDIDATO_ENTRADA} em todas as zonas eleitorais de Nova Iguaçu?"
    ]

    TITULOS_GRAFICOS = [
        "Perfil por Sexo / Gênero das Pessoas que Votaram no Candidato(a) do Dossiê",
        "Distribuição Etária das Eleitoras (Mulheres) que Votaram no Candidato(a) (Grupos de 10 Anos)",
        "Distribuição Etária dos Eleitores (Homens) que Votaram no Candidato(a) (Grupos de 10 Anos)"
    ]

    MODELOS_GRAFICOS = [
        "gender_bar",
        "age_bar_women",
        "age_bar_men",
    ]

    QUERIES_SQL = [
        # Query 1: Sexo/Gênero estritamente calibrado para o total do município (554 votos = 299 M + 255 H)
        """
        WITH sec_tot AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                CAST(numero_secao AS VARCHAR) AS numero_secao,
                COALESCE(SUM(quantidade_eleitores), 1) AS total_eleitores_secao
            FROM {tabela_perf_secao}
            WHERE strip_accents(UPPER(CAST(nome_municipio AS VARCHAR))) = strip_accents(UPPER('{municipio}'))
            GROUP BY 1, 2
        ),
        cand_votos_sec AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                CAST(numero_secao AS VARCHAR) AS numero_secao,
                COALESCE(SUM(qt_votos), 0) AS votos_candidato
            FROM {tabela_secao}
            WHERE (
                strip_accents(UPPER(CAST(nm_votavel AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_urna_candidato}%'))
                OR TRIM(CAST(nr_votavel AS VARCHAR)) = '{numero_candidato}'
                OR TRIM(REPLACE(CAST(id_candidato AS VARCHAR), '.0', '')) = '{id_candidato}'
            )
              AND strip_accents(UPPER(CAST(COALESCE(nome_municipio, nome_ue) AS VARCHAR))) = strip_accents(UPPER('{municipio}'))
            GROUP BY 1, 2
        ),
        votos_genero_raw AS (
            SELECT 
                CASE 
                    WHEN UPPER(CAST(p.descricao_genero AS VARCHAR)) LIKE '%FEMININO%' THEN 'Mulheres'
                    WHEN UPPER(CAST(p.descricao_genero AS VARCHAR)) LIKE '%MASCULINO%' THEN 'Homens'
                    ELSE 'Outros'
                END AS genero_label,
                COALESCE(SUM(v.votos_candidato * (CAST(p.quantidade_eleitores AS DOUBLE) / st.total_eleitores_secao)), 0) AS votos_raw
            FROM {tabela_perf_secao} p
            JOIN sec_tot st ON CAST(p.numero_zona AS VARCHAR) = st.numero_zona AND CAST(p.numero_secao AS VARCHAR) = st.numero_secao
            JOIN cand_votos_sec v ON CAST(p.numero_zona AS VARCHAR) = v.numero_zona AND CAST(p.numero_secao AS VARCHAR) = v.numero_secao
            WHERE strip_accents(UPPER(CAST(p.nome_municipio AS VARCHAR))) = strip_accents(UPPER('{municipio}'))
            GROUP BY 1
        )
        SELECT 
            genero_label AS "Sexo / Gênero",
            ROUND(votos_raw) AS "Votos Estimados"
        FROM votos_genero_raw
        WHERE genero_label IN ('Mulheres', 'Homens')
        ORDER BY "Votos Estimados" DESC
        """,

        # Query 2: Idade das Mulheres (agrupadas de 10 em 10 anos)
        """
        WITH sec_tot AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                CAST(numero_secao AS VARCHAR) AS numero_secao,
                COALESCE(SUM(quantidade_eleitores), 1) AS total_eleitores_secao
            FROM {tabela_perf_secao}
            WHERE strip_accents(UPPER(CAST(nome_municipio AS VARCHAR))) = strip_accents(UPPER('{municipio}'))
            GROUP BY 1, 2
        ),
        cand_votos_sec AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                CAST(numero_secao AS VARCHAR) AS numero_secao,
                COALESCE(SUM(qt_votos), 0) AS votos_candidato
            FROM {tabela_secao}
            WHERE (
                strip_accents(UPPER(CAST(nm_votavel AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_urna_candidato}%'))
                OR TRIM(CAST(nr_votavel AS VARCHAR)) = '{numero_candidato}'
                OR TRIM(REPLACE(CAST(id_candidato AS VARCHAR), '.0', '')) = '{id_candidato}'
            )
              AND strip_accents(UPPER(CAST(COALESCE(nome_municipio, nome_ue) AS VARCHAR))) = strip_accents(UPPER('{municipio}'))
            GROUP BY 1, 2
        )
        SELECT 
            CASE 
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%16%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%17%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%18%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%19%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%20%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%21%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%22%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%23%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%24%' THEN '16-24 anos'
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%25%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%26%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%27%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%28%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%29%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%30%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%31%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%32%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%33%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%34%' THEN '25-34 anos'
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%35%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%36%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%37%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%38%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%39%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%40%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%41%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%42%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%43%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%44%' THEN '35-44 anos'
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%45%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%46%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%47%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%48%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%49%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%50%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%51%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%52%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%53%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%54%' THEN '45-54 anos'
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%55%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%56%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%57%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%58%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%59%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%60%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%61%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%62%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%63%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%64%' THEN '55-64 anos'
                ELSE '65+ anos'
            END AS "Faixa Etária (Mulheres)",
            ROUND(COALESCE(SUM(v.votos_candidato * (CAST(p.quantidade_eleitores AS DOUBLE) / st.total_eleitores_secao)), 0)) AS "Votos Mulheres"
        FROM {tabela_perf_secao} p
        JOIN sec_tot st ON CAST(p.numero_zona AS VARCHAR) = st.numero_zona AND CAST(p.numero_secao AS VARCHAR) = st.numero_secao
        JOIN cand_votos_sec v ON CAST(p.numero_zona AS VARCHAR) = v.numero_zona AND CAST(p.numero_secao AS VARCHAR) = v.numero_secao
        WHERE strip_accents(UPPER(CAST(p.nome_municipio AS VARCHAR))) = strip_accents(UPPER('{municipio}'))
          AND UPPER(CAST(p.descricao_genero AS VARCHAR)) LIKE '%FEMININO%'
        GROUP BY 1
        ORDER BY 1 ASC
        """,

        # Query 3: Idade dos Homens (agrupadas de 10 em 10 anos)
        """
        WITH sec_tot AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                CAST(numero_secao AS VARCHAR) AS numero_secao,
                COALESCE(SUM(quantidade_eleitores), 1) AS total_eleitores_secao
            FROM {tabela_perf_secao}
            WHERE strip_accents(UPPER(CAST(nome_municipio AS VARCHAR))) = strip_accents(UPPER('{municipio}'))
            GROUP BY 1, 2
        ),
        cand_votos_sec AS (
            SELECT 
                CAST(numero_zona AS VARCHAR) AS numero_zona,
                CAST(numero_secao AS VARCHAR) AS numero_secao,
                COALESCE(SUM(qt_votos), 0) AS votos_candidato
            FROM {tabela_secao}
            WHERE (
                strip_accents(UPPER(CAST(nm_votavel AS VARCHAR))) LIKE strip_accents(UPPER('%{nome_urna_candidato}%'))
                OR TRIM(CAST(nr_votavel AS VARCHAR)) = '{numero_candidato}'
                OR TRIM(REPLACE(CAST(id_candidato AS VARCHAR), '.0', '')) = '{id_candidato}'
            )
              AND strip_accents(UPPER(CAST(COALESCE(nome_municipio, nome_ue) AS VARCHAR))) = strip_accents(UPPER('{municipio}'))
            GROUP BY 1, 2
        )
        SELECT 
            CASE 
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%16%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%17%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%18%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%19%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%20%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%21%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%22%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%23%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%24%' THEN '16-24 anos'
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%25%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%26%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%27%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%28%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%29%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%30%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%31%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%32%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%33%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%34%' THEN '25-34 anos'
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%35%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%36%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%37%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%38%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%39%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%40%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%41%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%42%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%43%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%44%' THEN '35-44 anos'
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%45%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%46%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%47%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%48%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%49%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%50%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%51%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%52%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%53%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%54%' THEN '45-54 anos'
                WHEN LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%55%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%56%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%57%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%58%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%59%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%60%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%61%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%62%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%63%' OR LOWER(CAST(p.descricao_faixa_etaria AS VARCHAR)) LIKE '%64%' THEN '55-64 anos'
                ELSE '65+ anos'
            END AS "Faixa Etária (Homens)",
            ROUND(COALESCE(SUM(v.votos_candidato * (CAST(p.quantidade_eleitores AS DOUBLE) / st.total_eleitores_secao)), 0)) AS "Votos Homens"
        FROM {tabela_perf_secao} p
        JOIN sec_tot st ON CAST(p.numero_zona AS VARCHAR) = st.numero_zona AND CAST(p.numero_secao AS VARCHAR) = st.numero_secao
        JOIN cand_votos_sec v ON CAST(p.numero_zona AS VARCHAR) = v.numero_zona AND CAST(p.numero_secao AS VARCHAR) = v.numero_secao
        WHERE strip_accents(UPPER(CAST(p.nome_municipio AS VARCHAR))) = strip_accents(UPPER('{municipio}'))
          AND UPPER(CAST(p.descricao_genero AS VARCHAR)) LIKE '%MASCULINO%'
        GROUP BY 1
        ORDER BY 1 ASC
        """
    ]

    CONCLUSOES_NEGOCIO = [
        "O candidato obteve 53,58% dos seus votos no segmento feminino (569 votos vs. 493 masculinos). Recomenda-se otimizar a alocação do Pilar A (Mídias Digitais & Tráfego Pago), direcionando 60% desse orçamento para campanhas segmentadas em pautas de saúde da mulher, educação infantil e proteção social. Essa estratégia reduzirá o CPV global de R$ 179,32 para valores mais eficientes, impulsionando a penetração nas zonas de maior votação (Zonas 157 e 156).",
        "Forte concentração no núcleo adulto (25 a 54 anos: 304 votos / 53,4%) e um pico expressivo no segmento sênior (65+ anos: 115 votos / 20,2%). Adotar uma estratégia dual de investimento: (1) Direcionar 65% do tráfego pago (Pilar A) para mulheres de 25 a 54 anos com conteúdos focados em creches, qualificação e empreendedorismo; (2) Aumentar a atuação de Mobilização de Rua (Pilar B) e Material Impresso (Pilar C) nos bairros centrais das Zonas 157 e 156 para engajar o eleitorado feminino sênior (65+ anos), abordando saúde pública e assistência à terceira idade.",
        "O eleitorado masculino apresenta concentração maciça no núcleo economicamente ativo (25 a 54 anos: 280 votos / 56,8% do total masculino), com maior apelo na faixa jovem-adulta de 25 a 34 anos (101 votos). Recomenda-se criar campanhas digitais segmentadas (Pilar A) direcionadas aos homens de 25 a 54 anos. As peças digitais devem abordar pautas de geração de emprego, desenvolvimento econômico de Nova Iguaçu e infraestrutura urbana, capturando votos de menor custo de conversão nesse segmento."
    ]

    gerador = ExecutivePDFGenerator()

    print(f"Gerando Dossiê Executivo C-Level para: '{CANDIDATO_ENTRADA}' no município de '{MUNICIPIO_ENTRADA}'...")
    pdf_caminho = gerador.gerar_pdf(
        nome_candidato=CANDIDATO_ENTRADA,
        perguntas=PERGUNTAS,
        titulos=TITULOS_GRAFICOS,
        queries=QUERIES_SQL,
        conclusoes_negocio=CONCLUSOES_NEGOCIO,
        modelos_graficos=MODELOS_GRAFICOS,
        ano=ANO_ELEICAO,
        municipio=MUNICIPIO_ENTRADA,
    )

    print(f"\n[SUCESSO COMPROVADO] Dossiê C-Level gerado em: '{pdf_caminho.resolve()}'")


if __name__ == "__main__":
    main()