import os
import glob
import shutil
import re
import pandas as pd
import pdfplumber
from utils import remover_acentos, intel_v_f


class FiscalModulo:
    def __init__(self, parent):
        self.parent = parent
        self.pasta_exe = parent.pasta_exe

        # Define as pastas de entrada e backup
        self.ENTRADA = os.path.join(self.pasta_exe, "entrada de arquivos")
        self.BKP = os.path.join(self.ENTRADA, "arquivos_processados")

        for p in [self.ENTRADA, self.BKP]:
            os.makedirs(p, exist_ok=True)

    def executar_fiscal(self, saida_path, log_func):
        os.makedirs(saida_path, exist_ok=True)
        arquivos = [f for f in glob.glob(os.path.join(self.ENTRADA, "*.*")) if os.path.isfile(f)]

        db = {
            "NFE_EMITIDA": None, "NFE_DESTINADA": None,
            "NFCE_EMITIDA_DF": None, "NFCE_DESTINADA_DF": None,
            "V_NFSE_DESTINADA": 0.0,
            "V_NFCE_EMITIDA_LIQ": 0.0, "V_NFCE_DESTINADA_LIQ": 0.0,
            "V_ESTORNADA_EMITIDA": 0.0,
            "V_ESTORNADA_EMITIDA_ICMS": 0.0,
            "V_ESTORNADA_EMITIDA_IPI": 0.0,
            "V_CTE_LIQ": 0.0
        }
        db_nomes, processados = {}, []

        for path in arquivos:
            orig = os.path.basename(path)
            n_base = os.path.splitext(orig)[0].replace(" ", "_").upper()
            ext_m = os.path.splitext(orig)[1].lower()
            limpo = f"{n_base}{ext_m}"
            nome = remover_acentos(orig).upper()

            log_func(f"--- Lendo: {orig} ---")

            if ext_m in ['.zip', '.rar'] or "SEM MOVIMENTO" in nome:
                shutil.copy(path, os.path.join(saida_path, limpo))
                processados.append(path)
                continue

            # Processamento CTE
            if "CTE" in nome and ext_m in ['.xlsx', '.xls']:
                try:
                    df_full = pd.read_excel(path, header=None).fillna("")
                    df_data = df_full.iloc[3:]
                    cte_bruto = sum(intel_v_f(r.iloc[6]) for _, r in df_data.iterrows())
                    cte_canc = sum(
                        intel_v_f(r.iloc[6]) for _, r in df_data.iterrows() if "CANCELADO" in str(r.iloc[0]).upper())
                    db["V_CTE_LIQ"] += (cte_bruto - cte_canc)
                    self.salvar_cte_final(os.path.join(saida_path, f"{n_base}.xlsx"), df_full)
                except Exception as e:
                    log_func(f"Erro CTE: {e}")
                processados.append(path)
                continue

            # Processamento Serviço (PDF)
            if ext_m == ".pdf" and "SERVICO" in nome:
                if "PRESTADO" in nome:
                    shutil.copy(path, os.path.join(saida_path, limpo))
                    processados.append(path)
                    log_func(f"Serviço PRESTADO identificado. Arquivo copiado.", "sucesso")
                    continue

                try:
                    total_bruto = 0.0
                    total_deducoes = 0.0

                    with pdfplumber.open(path) as pdf:
                        # 1. Total Rodapé
                        full_text = ""
                        for p in pdf.pages:
                            txt = p.extract_text() or ""
                            full_text += txt + "\n"

                        for l in full_text.split('\n'):
                            if "TOTAIS" in l.upper() and "QTD" in l.upper():
                                v = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', l)
                                if v:
                                    valores = [intel_v_f(x) for x in v]
                                    total_bruto = max(valores) if valores else 0.0
                                    log_func(f"VALOR TOTAL DETECTADO: R$ {total_bruto:,.2f}")

                        # 2. Scanner Deduções (Cancelados/Substituídos)
                        lines = full_text.split('\n')
                        caçando_valor = False

                        for linha_raw in lines:
                            linha = remover_acentos(linha_raw).upper().strip()
                            if "CANCELADO" in linha or "SUBSTITUIDO" in linha:
                                caçando_valor = True
                                log_func(f"[ALERTA] Status INVÁLIDO: '{linha[:40]}...'")

                            if caçando_valor:
                                matches = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', linha)
                                if matches:
                                    valores = [intel_v_f(x) for x in matches]
                                    valores_validos = [v for v in valores if v > 10.00]
                                    if valores_validos:
                                        valor_nota = max(valores_validos)
                                        total_deducoes += valor_nota
                                        log_func(f"[DEDUÇÃO] R$ {valor_nota:,.2f} abatido.", "sucesso")
                                        caçando_valor = False

                            if "NORMAL" in linha and "ATIVO" in linha and not caçando_valor:
                                pass

                    valor_liquido = max(0.0, total_bruto - total_deducoes)
                    db["V_NFSE_DESTINADA"] = valor_liquido
                    log_func(f"RESUMO SERVIÇO TOMADO: Líquido {valor_liquido:,.2f}", "info", divisor=True)

                except Exception as e:
                    log_func(f"Erro ao ler PDF Serviço: {e}", "erro")

                shutil.copy(path, os.path.join(saida_path, limpo))
                processados.append(path)
                continue

            # Processamento Excel NFE/NFCE
            if ext_m in ['.xlsx', '.xls']:
                try:
                    df = pd.read_excel(path, dtype=str).fillna("")

                    # 1. Definição do TIPO (EMITIDA ou DESTINADA)
                    if "EMITIDA" in nome or "EMITIDO" in nome:
                        t = "EMITIDA"
                    else:
                        t = "DESTINADA"

                    s_s = f"{n_base}.xlsx"

                    # Se for EMITIDA, calcula estornadas
                    if t == "EMITIDA":
                        temp_col = df.iloc[:, 21].copy().astype(object)
                        db["V_ESTORNADA_EMITIDA"] = sum(
                            intel_v_f(r) for idx, r in temp_col.items() if str(df.iloc[idx, 3]).upper() == "E")

                        # ICMS Estornado (Coluna X - Índice 23)
                        if len(df.columns) > 23:
                            db["V_ESTORNADA_EMITIDA_ICMS"] = sum(
                                intel_v_f(df.iloc[idx, 23]) for idx, r in temp_col.items() if
                                str(df.iloc[idx, 3]).upper() == "E")

                        # IPI Estornado (Coluna AR - Índice 43)
                        if len(df.columns) > 43:
                            db["V_ESTORNADA_EMITIDA_IPI"] = sum(
                                intel_v_f(df.iloc[idx, 43]) for idx, r in temp_col.items() if
                                str(df.iloc[idx, 3]).upper() == "E")

                    # 2. Definição do MODELO (NFE ou NFCE)
                    if "NFCE" in nome:
                        db[f"NFCE_{t}_DF"] = df
                        db_nomes[f"NFCE_{t}"] = s_s
                        idx_v = 21 if len(df.columns) > 21 else len(df.columns) - 1
                        temp_v = df.iloc[:, idx_v].copy().astype(object)
                        bruto = sum(intel_v_f(v) for v in temp_v)
                        canc = sum(intel_v_f(df.iloc[i, idx_v]) for i, r in df.iterrows() if
                                   "CANC" in str(df.iloc[i, 4]).upper())
                        db[f"V_NFCE_{t}_LIQ"] = bruto - canc

                    elif "NFE" in nome or "NOTA" in nome:
                        db[f"NFE_{t}"] = df
                        db_nomes[f"NFE_{t}"] = s_s

                    processados.append(path)
                except Exception as e:
                    log_func(f"Erro Excel NFE/NFCE: {e}")

        # GERAÇÃO DE RELATÓRIOS EXCEL
        for t in ["EMITIDA", "DESTINADA"]:
            if db[f"NFE_{t}"] is not None:
                self.salvar_nfe_f(
                    os.path.join(saida_path, db_nomes[f"NFE_{t}"]),
                    db[f"NFE_{t}"],
                    db[f"V_NFCE_{t}_LIQ"],
                    db[f"V_NFSE_DESTINADA"] if t == "DESTINADA" else 0,
                    db["V_ESTORNADA_EMITIDA"] if t == "DESTINADA" else 0,
                    db["V_CTE_LIQ"] if t == "DESTINADA" else 0,
                    db["V_ESTORNADA_EMITIDA_ICMS"] if t == "DESTINADA" else 0.0,
                    db["V_ESTORNADA_EMITIDA_IPI"] if t == "DESTINADA" else 0.0
                )
            if db[f"NFCE_{t}_DF"] is not None:
                self.salvar_nfce_f(os.path.join(saida_path, db_nomes[f"NFCE_{t}"]), db[f"NFCE_{t}_DF"])

        # === EXIBIÇÃO DAS TABELAS NO LOG (FINAL) ===
        log_func("", divisor=True)
        log_func("RESUMO FINAL DAS OPERAÇÕES", "info")

        # Tabela ENTRADAS (Baseada na NFE_DESTINADA)
        if db["NFE_DESTINADA"] is not None:
            self.exibir_resumo_log(
                log_func, "ENTRADAS (DESTINADAS)",
                db["NFE_DESTINADA"],
                db["V_NFSE_DESTINADA"],
                db["V_NFCE_DESTINADA_LIQ"],
                db["V_ESTORNADA_EMITIDA"],
                db["V_CTE_LIQ"]
            )
        else:
            log_func("\n[ENTRADAS] Sem dados de NFE Destinada para exibir.")

        # Tabela SAÍDAS (Baseada na NFE_EMITIDA)
        if db["NFE_EMITIDA"] is not None:
            self.exibir_resumo_log(
                log_func, "SAÍDAS (EMITIDAS)",
                db["NFE_EMITIDA"],
                0.0,
                db["V_NFCE_EMITIDA_LIQ"],
                0.0,
                0.0
            )
        else:
            log_func("\n[SAÍDAS] Sem dados de NFE Emitida para exibir.")

        # BACKUP
        for p in processados:
            d = os.path.join(self.BKP, os.path.basename(p))
            if os.path.exists(d): os.remove(d)
            shutil.move(p, d)

        log_func("=== CONCLUÍDO ===")

    def exibir_resumo_log(self, log_func, titulo, df, v_nfse, v_nfce, v_dev, v_cte):
        """Calcula e imprime a tabela resumo no log, idêntica à do Excel"""
        try:
            idx_val = 21 if len(df.columns) > 21 else len(df.columns) - 1
            col_val = df.iloc[:, idx_val].astype(str).apply(intel_v_f)
            v_nfe_total = col_val.sum()
            v_estornadas = sum(
                intel_v_f(df.iloc[i, idx_val]) for i, r in df.iterrows() if str(df.iloc[i, 3]).upper() == "E")
            v_canceladas = sum(
                intel_v_f(df.iloc[i, idx_val]) for i, r in df.iterrows() if "CANC" in str(df.iloc[i, 4]).upper())
            v_total_geral = v_nfe_total - v_estornadas - v_canceladas + v_nfse + v_nfce + v_dev + v_cte

            log_func(f"\n===== {titulo} =====")
            log_func(f"{'DESCRIÇÃO':<20} | {'VALOR (R$)':>15}")
            log_func("-" * 40)
            log_func(f"{'NFE':<20} | {v_nfe_total:>15.2f}")
            log_func(f"{'ESTORNADAS':<20} | {v_estornadas:>15.2f}")
            log_func(f"{'CANCELADAS':<20} | {v_canceladas:>15.2f}")
            log_func(f"{'NFSE':<20} | {v_nfse:>15.2f}")
            log_func(f"{'NFCE':<20} | {v_nfce:>15.2f}")
            if v_dev > 0:
                log_func(f"{'DEVOLUCAO':<20} | {v_dev:>15.2f}")
            if v_cte > 0:
                log_func(f"{'CTE':<20} | {v_cte:>15.2f}")
            log_func("-" * 40)
            log_func(f"{'TOTAL GERAL':<20} | {v_total_geral:>15.2f}")
            log_func("=" * 40)

        except Exception as e:
            log_func(f"Erro ao gerar tabela log para {titulo}: {e}", "erro")

    def salvar_cte_final(self, p, df_full):
        with pd.ExcelWriter(p, engine='xlsxwriter') as writer:
            df_full.to_excel(writer, index=False, header=False, sheet_name='Relatorio')
            wb, ws = writer.book, writer.sheets['Relatorio']
            fmt_h = wb.add_format({'bg_color': '#92D050', 'bold': True, 'border': 1})
            fmt_m = wb.add_format({'num_format': '#,##0.00'})
            ws.set_column(6, 6, 15, fmt_m)
            for c, v in enumerate(df_full.iloc[2]): ws.write(2, c, v, fmt_h)
            for r_idx in range(3, len(df_full)):
                ws.write(r_idx, 6, intel_v_f(df_full.iloc[r_idx, 6]), fmt_m)
                ws.write(r_idx, 0, str(df_full.iloc[r_idx, 0]).upper())
            last = len(df_full);
            res = last + 1
            ws.write(res + 1, 0, "CTE");
            ws.write_formula(res + 1, 1, f"=SUM(G4:G{last})", fmt_m)
            ws.write(res + 2, 0, "CANCELADO");
            ws.write_formula(res + 2, 1, f'=SUMIF(A4:A{last}, "*CANCELADO*", G4:G{last})', fmt_m)
            ws.write(res + 3, 0, "TOTAL");
            ws.write_formula(res + 3, 1, f"=B{res + 2}-B{res + 3}", fmt_m)
            ws.add_table(res, 0, res + 3, 1,
                         {'header_row': True, 'columns': [{'header': 'RESUMO CTE'}, {'header': 'VALOR'}]})

    def salvar_nfe_f(self, p, df, v_nfce, v_nfse, v_dev, v_cte, v_dev_icms=0.0, v_dev_ipi=0.0):
        col_name = df.columns[21]
        df[col_name] = df[col_name].apply(intel_v_f).astype(float)

        if len(df.columns) > 23:
            col_x = df.columns[23]
            df[col_x] = df[col_x].apply(intel_v_f).astype(float)
        if len(df.columns) > 43:
            col_ar = df.columns[43]
            df[col_ar] = df[col_ar].apply(intel_v_f).astype(float)

        with pd.ExcelWriter(p, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Relatorio')
            wb, ws = writer.book, writer.sheets['Relatorio']
            fmt_h = wb.add_format({'bg_color': '#92D050', 'bold': True, 'border': 1})
            fmt_m = wb.add_format({'num_format': '#,##0.00'})

            ws.set_column(21, 21, 15, fmt_m)
            ws.set_column(23, 23, 15, fmt_m)
            ws.set_column(43, 43, 15, fmt_m)

            for c, v in enumerate(df.columns): ws.write(0, c, v, fmt_h)
            last, res = len(df) + 1, len(df) + 2

            # ================= TABELA 1: GERAL (A e B) =================
            ws.write(res, 0, "NFE")
            ws.write_formula(res, 1, f"=SUM(V2:V{last})", fmt_m)
            ws.write(res + 1, 0, "ESTORNADAS")
            ws.write_formula(res + 1, 1, f'=SUMIF(D2:D{last}, "E", V2:V{last})', fmt_m)
            ws.write(res + 2, 0, "CANCELADAS")
            ws.write_formula(res + 2, 1, f'=SUMIF(E2:E{last}, "*CANC*", V2:V{last})', fmt_m)
            ws.write(res + 3, 0, "NFSE")
            ws.write(res + 3, 1, v_nfse, fmt_m)
            ws.write(res + 4, 0, "NFCE")
            ws.write(res + 4, 1, v_nfce, fmt_m)
            off = 0
            if v_dev > 0: ws.write(res + 5, 0, "DEVOLUCAO"); ws.write(res + 5, 1, v_dev, fmt_m); off += 1
            if v_cte > 0: ws.write(res + 5 + off, 0, "CTE"); ws.write(res + 5 + off, 1, v_cte, fmt_m); off += 1
            ws.write(res + 5 + off, 0, "TOTAL")
            r = res + 1
            parts = [f"B{r}", f"-B{r + 1}", f"-B{r + 2}", f"+B{r + 3}", f"+B{r + 4}"]
            curr = r + 5
            if v_dev > 0: parts.append(f"+B{curr}"); curr += 1
            if v_cte > 0: parts.append(f"+B{curr}")
            ws.write_formula(res + 5 + off, 1, "=" + "".join(parts), fmt_m)
            ws.add_table(res - 1, 0, res + 5 + off, 1,
                         {'header_row': True, 'columns': [{'header': 'DESCRIÇÃO'}, {'header': 'VALOR'}]})

            # ================= TABELA 2: ICMS (D e E) =================
            ws.write(res, 3, "ICMS GERAL")
            ws.write_formula(res, 4, f"=SUM(X2:X{last})", fmt_m)
            ws.write(res + 1, 3, "CANCELADO")
            ws.write_formula(res + 1, 4, f'=SUMIF(E2:E{last}, "*CANC*", X2:X{last})', fmt_m)

            row_icms = res + 2
            parts_icms = [f"E{res + 1}", f"-E{res + 2}"]

            # Condição sincronizada com a Tabela 1
            if v_dev > 0 or v_dev_icms > 0:
                ws.write(row_icms, 3, "ICMS DEVOLUCAO")
                ws.write(row_icms, 4, v_dev_icms, fmt_m)
                parts_icms.append(f"+E{row_icms + 1}")
                row_icms += 1

            ws.write(row_icms, 3, "TOTAL")
            ws.write_formula(row_icms, 4, "=" + "".join(parts_icms), fmt_m)
            ws.add_table(res - 1, 3, row_icms, 4,
                         {'header_row': True, 'columns': [{'header': 'RESUMO ICMS'}, {'header': 'VALOR'}]})

            # ================= TABELA 3: IPI (G e H) =================
            ws.write(res, 6, "IPI GERAL")
            ws.write_formula(res, 7, f"=SUM(AR2:AR{last})", fmt_m)
            ws.write(res + 1, 6, "CANCELADO")
            ws.write_formula(res + 1, 7, f'=SUMIF(E2:E{last}, "*CANC*", AR2:AR{last})', fmt_m)

            row_ipi = res + 2
            parts_ipi = [f"H{res + 1}", f"-H{res + 2}"]

            # Condição sincronizada com a Tabela 1
            if v_dev > 0 or v_dev_ipi > 0:
                ws.write(row_ipi, 6, "IPI DEVOLUCAO")
                ws.write(row_ipi, 7, v_dev_ipi, fmt_m)
                parts_ipi.append(f"+H{row_ipi + 1}")
                row_ipi += 1

            ws.write(row_ipi, 6, "TOTAL")
            ws.write_formula(row_ipi, 7, "=" + "".join(parts_ipi), fmt_m)
            ws.add_table(res - 1, 6, row_ipi, 7,
                         {'header_row': True, 'columns': [{'header': 'RESUMO IPI'}, {'header': 'VALOR'}]})

    def salvar_nfce_f(self, p, df):
        idx = 21 if len(df.columns) > 21 else len(df.columns) - 1
        col_name = df.columns[idx]
        df[col_name] = df[col_name].apply(intel_v_f).astype(float)
        with pd.ExcelWriter(p, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Relatorio')
            wb, ws = writer.book, writer.sheets['Relatorio']
            fmt_h = wb.add_format({'bg_color': '#92D050', 'bold': True, 'border': 1})
            fmt_m = wb.add_format({'num_format': '#,##0.00'})
            ws.set_column(idx, idx, 15, fmt_m)
            for c, v in enumerate(df.columns): ws.write(0, c, v, fmt_h)
            last, res = len(df) + 1, len(df) + 2
            ws.write(res, 0, "NFCE");
            ws.write_formula(res, 1, f"=SUM(V2:V{last})", fmt_m)
            ws.write(res + 1, 0, "CANCELADA");
            ws.write_formula(res + 1, 1, f'=SUMIF(E2:E{last}, "*CANC*", V2:V{last})', fmt_m)
            ws.write(res + 2, 0, "TOTAL");
            ws.write_formula(res + 2, 1, f"=B{res + 1}-B{res + 2}", fmt_m)
            ws.add_table(res - 1, 0, res + 2, 1,
                         {'header_row': True, 'columns': [{'header': 'RESUMO NFCE'}, {'header': 'VALOR'}]})