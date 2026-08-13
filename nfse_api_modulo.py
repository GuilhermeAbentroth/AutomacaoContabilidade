import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import os
import re
import time
import threading
import tempfile
import requests
import base64
import gzip
import json
import io
import sqlite3
from datetime import datetime, date
import calendar
import shutil
import pandas as pd
from certificado_utils import CertificadoA1


class NFSeAPIModulo:
    """
    Consulta e baixa NFS-e do Portal Nacional via API oficial (mTLS).
    Gera o DANFSe idêntico ao Padrão Nacional localmente sem requisitar PDFs online.
    Gera relatório Excel contábil e separa PDFs com retenção.
    """

    BASE_URL_SEFIN = "https://www.nfse.gov.br/EmissorNacional/api/v1"
    BASE_URL_ADN = "https://adn.nfse.gov.br/contribuintes"

    DELAY_ENTRE_LOTES = 1.2
    MAX_RETRY_429 = 5
    DELAY_RETRY_429 = 65

    MESES_PT = {
        1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
        5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
        9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO",
    }

    def __init__(self, parent):
        self.parent = parent
        self._cert_temp = None
        self._key_temp = None
        self._session = None
        self._parar = False

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def tela_api(self):
        self.parent.limpar_tela()
        self._parar = False

        f_header = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_header.pack(pady=5, fill="x")
        ctk.CTkLabel(f_header, text="🔌 NFS-e via API Oficial — Portal Nacional",
                     font=("Arial", 20, "bold"), text_color="#005A9C").pack(pady=5)
        ctk.CTkLabel(f_header,
                     text="Download XML + PDF Local + Relatório Excel Contábil",
                     font=("Arial", 12), text_color="gray").pack()

        # --- CONFIGURAÇÃO ---
        f_cfg = ctk.CTkFrame(self.parent.container)
        f_cfg.pack(fill="x", padx=40, pady=8)
        ctk.CTkLabel(f_cfg, text="CONFIGURAÇÃO", font=("Arial", 11, "bold"),
                     text_color="#005A9C").pack(pady=4)

        f_cnpj = ctk.CTkFrame(f_cfg, fg_color="transparent")
        f_cnpj.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(f_cnpj, text="CNPJ do Cliente:", font=("Arial", 12, "bold"),
                     width=140, anchor="w").pack(side="left")
        self.ent_cnpj = ctk.CTkEntry(f_cnpj, placeholder_text="Detectado automaticamente do certificado", width=260)
        self.ent_cnpj.pack(side="left", padx=10)
        ctk.CTkButton(f_cnpj, text="🔍 Detectar", width=90,
                      command=self._detectar_cnpj_ui).pack(side="left")

        f_pfx = ctk.CTkFrame(f_cfg, fg_color="transparent")
        f_pfx.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(f_pfx, text="Certificado (.pfx):", font=("Arial", 12, "bold"),
                     width=140, anchor="w").pack(side="left")
        self.ent_pfx = ctk.CTkEntry(f_pfx, width=300)
        self.ent_pfx.pack(side="left", padx=10)
        ctk.CTkButton(f_pfx, text="...", width=40,
                      command=self._selecionar_pfx).pack(side="left")

        f_senha = ctk.CTkFrame(f_cfg, fg_color="transparent")
        f_senha.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(f_senha, text="Senha Certificado:", font=("Arial", 12, "bold"),
                     width=140, anchor="w").pack(side="left")
        self.ent_senha = ctk.CTkEntry(f_senha, show="*", width=200)
        self.ent_senha.pack(side="left", padx=10)

        # --- PERÍODO ---
        f_per = ctk.CTkFrame(self.parent.container)
        f_per.pack(fill="x", padx=40, pady=4)
        ctk.CTkLabel(f_per, text="PERÍODO (Data de Emissão)", font=("Arial", 11, "bold"),
                     text_color="#005A9C").pack(pady=4)

        f_datas = ctk.CTkFrame(f_per, fg_color="transparent")
        f_datas.pack(fill="x", padx=20, pady=4)

        hoje = date.today()
        mes_ant = hoje.month - 1 if hoje.month > 1 else 12
        ano_ant = hoje.year if hoje.month > 1 else hoje.year - 1
        dt_ini = date(ano_ant, mes_ant, 1).strftime("%d/%m/%Y")
        dt_fim = date(ano_ant, mes_ant,
                      calendar.monthrange(ano_ant, mes_ant)[1]).strftime("%d/%m/%Y")

        ctk.CTkLabel(f_datas, text="Início:", font=("Arial", 12)).pack(side="left")
        self.ent_dt_ini = ctk.CTkEntry(f_datas, width=110)
        self.ent_dt_ini.insert(0, dt_ini)
        self.ent_dt_ini.pack(side="left", padx=8)

        ctk.CTkLabel(f_datas, text="Fim:", font=("Arial", 12)).pack(side="left", padx=(10, 0))
        self.ent_dt_fim = ctk.CTkEntry(f_datas, width=110)
        self.ent_dt_fim.insert(0, dt_fim)
        self.ent_dt_fim.pack(side="left", padx=8)

        f_pasta = ctk.CTkFrame(f_per, fg_color="transparent")
        f_pasta.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(f_pasta, text="Salvar em:", font=("Arial", 12, "bold"),
                     width=140, anchor="w").pack(side="left")
        self.ent_pasta = ctk.CTkEntry(f_pasta, width=340)
        self.ent_pasta.insert(0, self.parent.configuracoes.get("ultimo_caminho", ""))
        self.ent_pasta.pack(side="left", padx=10)
        ctk.CTkButton(f_pasta, text="...", width=40,
                      command=self._selecionar_pasta).pack(side="left")

        # --- LOG ---
        f_log = ctk.CTkFrame(self.parent.container)
        f_log.pack(fill="both", expand=True, padx=40, pady=6)
        ctk.CTkLabel(f_log, text="Log:", font=("Arial", 11, "bold"),
                     text_color="gray").pack(anchor="w", padx=10, pady=2)
        self.parent.txt_log = scrolledtext.ScrolledText(
            f_log, height=10, state="disabled",
            bg="#1e1e1e", fg="white", font=("Consolas", 10))
        self.parent.txt_log.pack(fill="both", expand=True, padx=10, pady=4)

        # --- BOTÕES ---
        f_btns = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_btns.pack(pady=10)

        ctk.CTkButton(f_btns, text="📥 Baixar EMITIDAS",
                      command=lambda: self._iniciar("emitidas"),
                      width=180, height=45, font=("Arial", 13, "bold"),
                      fg_color="#f39200", hover_color="#cc7a00").pack(side="left", padx=6)

        ctk.CTkButton(f_btns, text="📨 Baixar DESTINADAS",
                      command=lambda: self._iniciar("tomadas"),
                      width=180, height=45, font=("Arial", 13, "bold"),
                      fg_color="#228B22", hover_color="#1e7a1e").pack(side="left", padx=6)

        ctk.CTkButton(f_btns, text="🔄 AMBAS",
                      command=lambda: self._iniciar("ambas"),
                      width=130, height=45, font=("Arial", 13, "bold"),
                      fg_color="#6c3483", hover_color="#512e5f").pack(side="left", padx=6)

        ctk.CTkButton(f_btns, text="⏹ PARAR",
                      command=self._parar_processo,
                      width=100, height=45, font=("Arial", 12, "bold"),
                      fg_color="#CC0000", hover_color="#a30000").pack(side="left", padx=6)

        ctk.CTkButton(f_btns, text="🗑️ Reset NSU",
                      command=self._reset_nsu,
                      width=110, height=45, fg_color="#7f8c8d",
                      font=("Arial", 11)).pack(side="left", padx=6)

        ctk.CTkButton(f_btns, text="Voltar",
                      command=self.parent.mostrar_menu_inicial,
                      width=90, height=45, fg_color="gray").pack(side="left", padx=6)

    def _selecionar_pfx(self):
        p = filedialog.askopenfilename(filetypes=[("Certificado A1", "*.pfx")])
        if p:
            self.ent_pfx.delete(0, tk.END)
            self.ent_pfx.insert(0, p)

    def _selecionar_pasta(self):
        p = filedialog.askdirectory()
        if p:
            self.ent_pasta.delete(0, tk.END)
            self.ent_pasta.insert(0, p)

    def _detectar_cnpj_certificado(self, pfx, senha):
        """Abre o .pfx e extrai o CNPJ embutido no certificado e-CNPJ. Retorna None se não achar."""
        try:
            cert_manager = CertificadoA1(pfx, senha)
            if not cert_manager.carregar_chaves():
                return None
            return cert_manager.obter_cnpj()
        except Exception:
            return None

    def _detectar_nome_certificado(self, pfx, senha):
        """Abre o .pfx e extrai a razão social embutida no CN do certificado e-CNPJ. Retorna '' se não achar."""
        try:
            cert_manager = CertificadoA1(pfx, senha)
            if not cert_manager.carregar_chaves():
                return ""
            return cert_manager.obter_nome_razao_social() or ""
        except Exception:
            return ""

    def _detectar_cnpj_ui(self):
        pfx = self.ent_pfx.get().strip()
        senha = self.ent_senha.get()
        if not pfx or not senha:
            messagebox.showwarning("Validação", "Selecione o Certificado e informe a Senha primeiro.")
            return
        cnpj = self._detectar_cnpj_certificado(pfx, senha)
        if cnpj:
            self.ent_cnpj.delete(0, tk.END)
            self.ent_cnpj.insert(0, cnpj)
        else:
            messagebox.showwarning("Não encontrado",
                                    "Não foi possível extrair o CNPJ do certificado.\n"
                                    "Verifique a senha ou informe o CNPJ manualmente (pode ser e-CPF).")

    def _parar_processo(self):
        self._parar = True
        self._log("⏹ Parada solicitada...", "erro")

    def _reset_nsu(self):
        pasta = self.ent_pasta.get().strip()
        cnpj = "".join(filter(str.isdigit, self.ent_cnpj.get()))
        rem = 0
        for sufixo in ("emitidas", "tomadas"):
            arq = os.path.join(pasta, f"_nsu_{cnpj}_{sufixo}.txt")
            if os.path.exists(arq):
                os.remove(arq)
                rem += 1
        messagebox.showinfo("Reset NSU",
                            f"NSU resetado ({rem} arquivo(s) removido(s)).\n"
                            "Próxima consulta buscará desde o início.")

    # ------------------------------------------------------------------
    # Fluxo principal
    # ------------------------------------------------------------------
    def _iniciar(self, tipo):
        cnpj = "".join(filter(str.isdigit, self.ent_cnpj.get()))
        pfx = self.ent_pfx.get().strip()
        senha = self.ent_senha.get()
        pasta = self.ent_pasta.get().strip()
        dt_ini = self.ent_dt_ini.get().strip()
        dt_fim = self.ent_dt_fim.get().strip()

        if not cnpj and pfx and senha:
            self._log("CNPJ não informado, tentando detectar a partir do certificado...", "info")
            cnpj_detectado = self._detectar_cnpj_certificado(pfx, senha)
            if cnpj_detectado:
                cnpj = cnpj_detectado
                self.ent_cnpj.delete(0, tk.END)
                self.ent_cnpj.insert(0, cnpj)
                self._log(f"✅ CNPJ detectado do certificado: {cnpj}", "sucesso")

        if not cnpj or not pfx or not senha or not pasta:
            messagebox.showwarning("Validação", "CNPJ, Certificado, Senha e Pasta são obrigatórios.")
            return
        if len(cnpj) != 14:
            messagebox.showwarning("Validação", "CNPJ deve ter 14 dígitos.")
            return

        self._parar = False
        self.parent.salvar_config("ultimo_caminho", pasta)
        threading.Thread(
            target=self._executar,
            args=(cnpj, pfx, senha, pasta, dt_ini, dt_fim, tipo),
            daemon=True
        ).start()

    def _executar(self, cnpj, pfx, senha, pasta, dt_ini, dt_fim, tipo):
        try:
            self._log("Carregando certificado digital...", "info")
            nome_empresa_cert = self._detectar_nome_certificado(pfx, senha)
            if not self._criar_sessao_mtls(pfx, senha):
                return
            self._log("✅ Certificado carregado. Sessão mTLS criada.", "sucesso")

            ini = datetime.strptime(dt_ini, "%d/%m/%Y").strftime("%Y-%m-%d")
            fim = datetime.strptime(dt_fim, "%d/%m/%Y").strftime("%Y-%m-%d")

            em, tom = self._processar_notas(cnpj, pasta, ini, fim, tipo, nome_empresa_cert)

            self._log("=" * 50, "info")
            if tipo in ("emitidas", "ambas"):
                self._log(f"📥 EMITIDAS: {em} nota(s) baixadas.", "sucesso" if em else "info")
            if tipo in ("tomadas", "ambas"):
                self._log(f"📨 TOMADAS:  {tom} nota(s) baixadas.", "sucesso" if tom else "info")
            self._log(f"✅ Total: {em + tom} nota(s).", "sucesso")

        except Exception as e:
            self._log(f"Erro crítico: {e}", "erro")
        finally:
            self._limpar_temp()

    # ------------------------------------------------------------------
    # mTLS
    # ------------------------------------------------------------------
    def _criar_sessao_mtls(self, pfx_path, senha):
        try:
            cert_manager = CertificadoA1(pfx_path, senha)
            if not cert_manager.carregar_chaves(self._log):
                return False

            cert_pem = cert_manager.obter_certificado_pem()
            key_pem = cert_manager.obter_chave_privada_pem()

            tf_cert = tempfile.NamedTemporaryFile(suffix="_cert.pem", delete=False, mode="wb")
            tf_cert.write(cert_pem.encode() if isinstance(cert_pem, str) else cert_pem)
            tf_cert.close()
            self._cert_temp = tf_cert.name

            tf_key = tempfile.NamedTemporaryFile(suffix="_key.pem", delete=False, mode="wb")
            tf_key.write(key_pem.encode() if isinstance(key_pem, str) else key_pem)
            tf_key.close()
            self._key_temp = tf_key.name

            self._session = requests.Session()
            self._session.cert = (self._cert_temp, self._key_temp)
            self._session.headers.update({
                "Accept": "application/json",
                "Content-Type": "application/json"
            })
            return True

        except Exception as e:
            self._log(f"Erro ao criar sessão mTLS: {e}", "erro")
            return False

    def _limpar_temp(self):
        for f in [self._cert_temp, self._key_temp]:
            try:
                if f and os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
        self._cert_temp = None
        self._key_temp = None

    def _aguardar_cancelavel(self, segundos):
        """Espera em passos curtos para poder ser interrompida rapidamente por _parar."""
        restante = segundos
        passo = 0.1
        while restante > 0:
            if self._parar:
                return
            time.sleep(min(passo, restante))
            restante -= passo

    # ------------------------------------------------------------------
    # GET com retry automático em 429
    # ------------------------------------------------------------------
    def _get_com_retry(self, url):
        for tentativa in range(self.MAX_RETRY_429):
            if self._parar:
                return None
            try:
                resp = self._session.get(url, timeout=30)
            except Exception as e:
                self._log(f"Erro de conexão: {e}", "erro")
                return None

            if resp.status_code == 429:
                if tentativa < self.MAX_RETRY_429 - 1:
                    self._log(f"⏳ Rate limit (429) — aguardando {self.DELAY_RETRY_429}s...", "info")
                    for _ in range(self.DELAY_RETRY_429):
                        if self._parar: return None
                        time.sleep(1)
                else:
                    return resp
            else:
                return resp
        return None

    # ------------------------------------------------------------------
    # Download principal
    # ------------------------------------------------------------------
    def _processar_notas(self, cnpj, pasta_base, dt_ini, dt_fim, tipo, nome_empresa_cert=""):
        self._log(f"\nConsultando ADN — período {dt_ini} a {dt_fim} — modo: {tipo.upper()}", "info", divisor=True)

        pasta_em = os.path.join(pasta_base, "NFSE_EMITIDAS")
        pasta_tom = os.path.join(pasta_base, "NFSE_TOMADAS")
        if tipo in ("emitidas", "ambas"): os.makedirs(pasta_em, exist_ok=True)
        if tipo in ("tomadas", "ambas"): os.makedirs(pasta_tom, exist_ok=True)

        arquivo_nsu = os.path.join(pasta_base, f"_nsu_{cnpj}_emitidas.txt" if tipo in ("emitidas",
                                                                                       "ambas") else f"_nsu_{cnpj}_tomadas.txt")
        nsu_atual = 0
        if os.path.exists(arquivo_nsu):
            try:
                with open(arquivo_nsu) as f:
                    nsu_atual = int(f.read().strip())
                self._log(
                    f"Retomando do NSU {nsu_atual} (execução anterior).\n⚡ Documentos anteriores já foram baixados.",
                    "info")
            except Exception:
                nsu_atual = 0

        dt_ini_dt = datetime.strptime(dt_ini, "%Y-%m-%d").date()
        dt_fim_dt = datetime.strptime(dt_fim, "%Y-%m-%d").date()

        baixados_em = 0
        baixados_tom = 0
        nsu_max = nsu_atual
        paginas = 0
        chaves_canceladas: set = set()
        pendentes_pdf: list = []

        while paginas < 1000 and not self._parar:
            paginas += 1

            if paginas > 1:
                self._aguardar_cancelavel(self.DELAY_ENTRE_LOTES)

            if self._parar: break

            url = f"{self.BASE_URL_ADN}/DFe/{nsu_atual}?cnpjConsulta={cnpj}"
            self._log(f"Lote {paginas} — NSU {nsu_atual}...", "info")

            resp = self._get_com_retry(url)
            if resp is None: break

            self._log(f"  HTTP {resp.status_code}", "info")

            if resp.status_code in (204, 404):
                self._log("Sem mais documentos.", "info")
                break
            if resp.status_code in (401, 403):
                self._log(f"❌ HTTP {resp.status_code} — Acesso negado.", "erro")
                break
            if resp.status_code == 429:
                self._log("❌ 429 persistente após retentativas. Parando.", "erro")
                break
            if resp.status_code != 200:
                self._log(f"Erro HTTP {resp.status_code}: {resp.text[:200]}", "erro")
                break

            try:
                dados = resp.json()
            except Exception as e:
                self._log(f"Resposta não JSON: {e}", "erro")
                break

            if paginas == 1:
                self._log(f"Status: {dados.get('StatusProcessamento')}", "info")

            dfe_list = dados.get("LoteDFe", [])
            if not dfe_list:
                self._log("Sem mais documentos.", "info")
                break

            total_lote = len(dfe_list)
            pulados = 0
            datas_lote = []

            self._log(f"  {total_lote} documento(s) no lote.", "info")

            for dfe in dfe_list:
                if self._parar: break
                try:
                    nsu_item = int(dfe.get("NSU", 0))
                    chave = dfe.get("ChaveAcesso", "")
                    tp_dfe = dfe.get("TipoDocumento", "NFSE").upper()
                    xml_b64 = dfe.get("ArquivoXml", "")

                    if nsu_item > nsu_max:
                        nsu_max = nsu_item

                    if not xml_b64:
                        pulados += 1
                        continue

                    if "EVENTO" in tp_dfe:
                        try:
                            ev_bytes = self._decodificar_conteudo(xml_b64.encode())
                            ev_str = ev_bytes.decode("utf-8", errors="ignore")
                            for padrao in [r'<chNFSe>([^<]+)</chNFSe>', r'<chave>([^<]+)</chave>',
                                           r'<(?:\w+:)?ChaveAcesso>([^<]+)</(?:\w+:)?ChaveAcesso>']:
                                m = re.search(padrao, ev_str)
                                if m:
                                    ch = m.group(1).strip()
                                    chaves_canceladas.add(ch)
                                    self._log(f"  🚫 Cancelamento detectado: ...{ch[-10:]}", "info")
                                    break
                        except Exception:
                            pass
                        pulados += 1
                        continue

                    conteudo = self._decodificar_conteudo(xml_b64.encode())
                    xml_str = conteudo.decode("utf-8", errors="ignore")

                    numero_nfse = self._extrair_numero_nfse(xml_str, chave)
                    m_data = (re.search(r'<dhProc>(\d{4}-\d{2}-\d{2})', xml_str)
                              or re.search(r'<dhEmi>(\d{4}-\d{2}-\d{2})', xml_str))
                    dt_doc = None
                    if m_data:
                        try:
                            dt_doc = datetime.strptime(m_data.group(1), "%Y-%m-%d").date()
                            datas_lote.append(dt_doc)
                        except Exception:
                            pass

                    if dt_doc and not (dt_ini_dt <= dt_doc <= dt_fim_dt):
                        pulados += 1
                        continue

                    m_prest = re.search(r'<prest>.*?<CNPJ>(\d+)</CNPJ>', xml_str, re.DOTALL)
                    cnpj_prest = m_prest.group(1) if m_prest else ""
                    eh_emitida = cnpj_prest == cnpj

                    salvar_em = (tipo in ("emitidas", "ambas")) and eh_emitida
                    salvar_tom = (tipo in ("tomadas", "ambas")) and not eh_emitida

                    if not salvar_em and not salvar_tom:
                        pulados += 1
                        continue

                    nome_base = chave if chave else f"NFSE_{numero_nfse}_NSU{nsu_item}"
                    is_cancel = chave in chaves_canceladas

                    if salvar_em:
                        caminho = os.path.join(pasta_em, nome_base + ".xml")
                        with open(caminho, "wb") as f: f.write(conteudo)
                        status_txt = " [CANCELADA]" if is_cancel else ""
                        self._log(f"  ✅ EMITIDA  NFS-e nº {numero_nfse}{status_txt}", "sucesso")
                        pendentes_pdf.append((chave, pasta_em, nome_base, conteudo, False))
                        baixados_em += 1

                    if salvar_tom:
                        caminho = os.path.join(pasta_tom, nome_base + ".xml")
                        with open(caminho, "wb") as f: f.write(conteudo)
                        status_txt = " [CANCELADA]" if is_cancel else ""
                        self._log(f"  ✅ TOMADA   NFS-e nº {numero_nfse}{status_txt}", "sucesso")
                        pendentes_pdf.append((chave, pasta_tom, nome_base, conteudo, True))
                        baixados_tom += 1

                except Exception as e:
                    self._log(f"  Erro NSU {dfe.get('NSU', '?')}: {e}", "erro")

            if pulados:
                self._log(f"  {pulados} documento(s) fora do período ou ignorados.", "info")

            if datas_lote and max(datas_lote) > dt_fim_dt:
                self._log(f"Período encerrado (último doc: {max(datas_lote)}).", "info")
                self._salvar_nsu(pasta_base, cnpj, tipo, nsu_max)
                self._log(f"NSU → {nsu_max} (salvo).", "info")
                break

            if nsu_max > nsu_atual:
                nsu_atual = nsu_max
                self._salvar_nsu(pasta_base, cnpj, tipo, nsu_atual)
                self._log(f"NSU → {nsu_atual}", "info")
            else:
                self._log("Fim dos documentos.", "info")
                break

        # =========================================================================
        # GERA TODOS OS PDFs E MONTA O RELATÓRIO EM EXCEL
        # =========================================================================
        dados_excel = []

        if pendentes_pdf:
            self._log(f"\nGerando {len(pendentes_pdf)} PDF(s) com layout do Padrão Nacional...", "info")
            for ch, pasta, nome, conteudo, eh_tomada in pendentes_pdf:
                is_cancel = ch in chaves_canceladas
                dados_nota = self._baixar_pdf(ch, pasta, nome, conteudo, is_cancel)

                if dados_nota:
                    v_serv = dados_nota["Valor Serviço"]
                    v_liq = dados_nota["Valor Líquido"]

                    # Condição clássica: se cobrou mais que o líquido, houve retenção
                    retencao = "SIM" if v_serv > v_liq else "NÃO"

                    def formatar_vazio(valor):
                        return valor if float(valor) > 0 else ""

                    v_iss_ret = dados_nota["ISS"] if dados_nota["ISS Retido"] == "Sim" else 0.0
                    v_inss = dados_nota["INSS (CP)"]
                    v_csrf = dados_nota["CSLL"] + dados_nota["PIS"] + dados_nota["COFINS"]
                    v_irrf = dados_nota["IRRF"]
                    v_desc = dados_nota.get("Desconto", 0.0)

                    dados_excel.append({
                        "Data Emissão": dados_nota["Data Emissão"][:10],
                        "Número NFS-e": dados_nota["NFS-e"],
                        "Prestador": f"{dados_nota['Prestador Nome']} - {dados_nota['Prestador CNPJ']}",
                        "Tomador": f"{dados_nota['Tomador Nome']} - {dados_nota['Tomador CNPJ/CPF']}",
                        "Valor Serviço (R$)": v_serv,
                        "Valor Líquido (R$)": v_liq,
                        "ISS Ret": formatar_vazio(v_iss_ret),
                        "INSS": formatar_vazio(v_inss),
                        "CSRF": formatar_vazio(v_csrf),
                        "IRRF": formatar_vazio(v_irrf),
                        "Desconto": formatar_vazio(v_desc),
                        "RETENÇÃO": retencao,
                        "Status": dados_nota["Status"]
                    })

                    # Cria pasta específica para notas com Retenção e copia o PDF
                    if retencao == "SIM":
                        pasta_retencao = os.path.join(pasta_base, "Com Retenção")
                        os.makedirs(pasta_retencao, exist_ok=True)
                        caminho_pdf_origem = os.path.join(pasta, nome + ".pdf")
                        if os.path.exists(caminho_pdf_origem):
                            shutil.copy2(caminho_pdf_origem, os.path.join(pasta_retencao, nome + ".pdf"))

                    # Notas TOMADAS com retenções federais (INSS/IRRF/CSLL/PIS/COFINS) são as
                    # que precisam ser declaradas na REINF pela empresa (tomador do serviço).
                    if eh_tomada and dados_nota.get("Total Retenções Federais", 0.0) > 0:
                        self._registrar_reinf(dados_nota, cnpj, nome_empresa_cert, pasta, nome)

        # -------------------------------------------------------------------------
        # SALVA O RELATÓRIO EXCEL COM RESUMO CONTÁBIL
        # -------------------------------------------------------------------------
        if dados_excel:
            self._log("Gerando Excel Contábil com Resumo...", "info", divisor=True)
            try:
                df = pd.DataFrame(dados_excel)
                prefixo_excel = "SERVICO PRESTADO" if tipo == "emitidas" else (
                    "SERVICO TOMADO" if tipo == "tomadas" else "NFSE_AMBAS")
                nome_excel = f"{prefixo_excel}_{datetime.now().strftime('%d%m%Y_%H%M')}.xlsx"
                caminho_final_excel = os.path.join(pasta_base, nome_excel)

                with pd.ExcelWriter(caminho_final_excel, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False, sheet_name='Relatorio')
                    wb = writer.book
                    ws = writer.sheets['Relatorio']

                    fmt_h = wb.add_format({'bg_color': '#92D050', 'bold': True, 'border': 1})
                    fmt_m = wb.add_format({'num_format': '#,##0.00'})

                    ws.set_column('A:B', 15)
                    ws.set_column('C:D', 40)
                    ws.set_column('E:K', 18, fmt_m)
                    ws.set_column('L:M', 18)

                    for c, v in enumerate(df.columns):
                        ws.write(0, c, v, fmt_h)

                    last = len(df) + 1
                    res = len(df) + 3

                    # Bloco do Somatório/Resumo
                    ws.write(res, 0, "NFSE")
                    ws.write_formula(res, 1, f"=SUM(E2:E{last})", fmt_m)

                    ws.write(res + 1, 0, "CANCELADA OU SUBSTITUÍDA")
                    # Fórmula para subtrair do montante aquelas com status Cancelada
                    ws.write_formula(res + 1, 1,
                                     f'=SUMIF(M2:M{last}, "*Cancelada*", E2:E{last}) + SUMIF(M2:M{last}, "*Substitui*", E2:E{last})',
                                     fmt_m)

                    ws.write(res + 2, 0, "TOTAL")
                    ws.write_formula(res + 2, 1, f"=B{res + 1}-B{res + 2}", fmt_m)

                    ws.add_table(res - 1, 0, res + 2, 1,
                                 {'header_row': True,
                                  'columns': [{'header': 'RESUMO NFSE'}, {'header': 'VALOR'}]})

                self._log(f"📊 Excel Contábil gerado em: {pasta_base}", "sucesso")
            except Exception as e_ex:
                self._log(f"⚠️ Erro ao gerar Excel: {e_ex}", "erro")

        return baixados_em, baixados_tom

    # ------------------------------------------------------------------
    # REINF — Retenções federais de notas TOMADAS (módulo Pessoal)
    # ------------------------------------------------------------------
    def _sanitizar_nome_pasta(self, nome):
        nome = re.sub(r'[<>:"/\\|?*]', '_', (nome or "").strip())
        return nome[:80].strip(" .") or "SEM_NOME"

    def _competencia_info(self, dt_compet_br):
        """A partir de 'dd/mm/aaaa' retorna (competencia_iso 'aaaa-mm', pasta 'MES AAAA')."""
        try:
            dt = datetime.strptime(dt_compet_br[:10], "%d/%m/%Y")
            return dt.strftime("%Y-%m"), f"{self.MESES_PT[dt.month]} {dt.year}"
        except Exception:
            return "SEM_COMPETENCIA", "SEM COMPETENCIA"

    def _registrar_reinf(self, dados_nota, empresa_cnpj, nome_empresa_cert, pasta_origem, nome_base):
        """Grava a retenção federal (INSS/IRRF/CSLL/PIS/COFINS) no banco compartilhado e copia
        o PDF/XML da nota para a pasta configurada de REINF, organizada por COMPETENCIA/EMPRESA."""
        empresa_nome = nome_empresa_cert or dados_nota.get("Tomador Nome") or empresa_cnpj
        competencia_iso, competencia_pasta = self._competencia_info(dados_nota.get("Competência", ""))

        caminho_pdf_origem = os.path.join(pasta_origem, nome_base + ".pdf")
        caminho_xml_origem = os.path.join(pasta_origem, nome_base + ".xml")

        try:
            db_path = self.parent.configuracoes.get("caminho_banco")
            conn = sqlite3.connect(db_path, timeout=10)
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reinf_retencoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chave_acesso TEXT UNIQUE,
                    empresa_cnpj TEXT,
                    empresa_nome TEXT,
                    competencia TEXT,
                    numero_nfse TEXT,
                    data_emissao TEXT,
                    prestador_cnpj TEXT,
                    prestador_nome TEXT,
                    valor_servico REAL,
                    valor_liquido REAL,
                    v_inss REAL,
                    v_irrf REAL,
                    v_csll REAL,
                    v_pis REAL,
                    v_cofins REAL,
                    v_total_retencoes REAL,
                    status TEXT,
                    caminho_pdf TEXT,
                    caminho_xml TEXT,
                    data_registro TEXT
                )
            """)
            cur.execute("""
                INSERT OR REPLACE INTO reinf_retencoes (
                    chave_acesso, empresa_cnpj, empresa_nome, competencia, numero_nfse,
                    data_emissao, prestador_cnpj, prestador_nome, valor_servico, valor_liquido,
                    v_inss, v_irrf, v_csll, v_pis, v_cofins, v_total_retencoes, status,
                    caminho_pdf, caminho_xml, data_registro
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                dados_nota.get("Chave", "") or nome_base,
                empresa_cnpj, empresa_nome, competencia_iso, dados_nota.get("NFS-e", ""),
                dados_nota.get("Data Emissão", "")[:10], dados_nota.get("Prestador CNPJ", ""),
                dados_nota.get("Prestador Nome", ""), dados_nota.get("Valor Serviço", 0.0),
                dados_nota.get("Valor Líquido", 0.0), dados_nota.get("INSS (CP)", 0.0),
                dados_nota.get("IRRF", 0.0), dados_nota.get("CSLL", 0.0), dados_nota.get("PIS", 0.0),
                dados_nota.get("COFINS", 0.0), dados_nota.get("Total Retenções Federais", 0.0),
                dados_nota.get("Status", ""), caminho_pdf_origem, caminho_xml_origem,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            conn.commit()
            conn.close()
            self._log(f"    🧾 Retenção REINF registrada: {empresa_nome} — {competencia_pasta}", "info")
        except Exception as e:
            self._log(f"    ⚠️ Erro ao registrar retenção REINF no banco: {e}", "erro")

        pasta_reinf = (self.parent.configuracoes.get("pasta_reinf") or "").strip()
        if pasta_reinf:
            try:
                destino = os.path.join(pasta_reinf, competencia_pasta, self._sanitizar_nome_pasta(empresa_nome))
                os.makedirs(destino, exist_ok=True)
                if os.path.exists(caminho_pdf_origem):
                    shutil.copy2(caminho_pdf_origem, os.path.join(destino, nome_base + ".pdf"))
                if os.path.exists(caminho_xml_origem):
                    shutil.copy2(caminho_xml_origem, os.path.join(destino, nome_base + ".xml"))
            except Exception as e:
                self._log(f"    ⚠️ Erro ao copiar nota para pasta REINF: {e}", "erro")

    def _extrair_numero_nfse(self, xml_str: str, chave: str) -> str:
        m = re.search(r'<nNFSe>(\d+)</nNFSe>', xml_str)
        if m: return m.group(1).lstrip("0") or m.group(1)
        m = re.search(r'<nDPS>(\d+)</nDPS>', xml_str)
        if m: return m.group(1).lstrip("0") or m.group(1)
        if chave: return chave[-10:].lstrip("0") or chave[-10:]
        return "SEM_NUMERO"

    # ------------------------------------------------------------------
    # Tabela IBGE de Municípios (código -> "Nome/UF")
    # ------------------------------------------------------------------
    def _carregar_ibge(self):
        if getattr(self, "_ibge_map", None) is not None:
            return self._ibge_map
        self._ibge_map = {}
        try:
            caminho = self.parent.resource_path("ibge_municipios.json")
            with open(caminho, encoding="utf-8") as f:
                self._ibge_map = json.load(f)
        except Exception:
            self._ibge_map = {}
        return self._ibge_map

    def _municipio_uf(self, codigo: str, nome_fallback: str = "", uf_fallback: str = "") -> str:
        """Retorna 'Município - UF' a partir do código IBGE, com fallback para nome já presente no XML."""
        codigo = (codigo or "").strip()
        if codigo:
            info = self._carregar_ibge().get(codigo)
            if info:
                nome, _, uf = info.partition("/")
                return f"{nome} - {uf}"
        if nome_fallback:
            return f"{nome_fallback} - {uf_fallback}" if uf_fallback else nome_fallback
        return "-"

    # ------------------------------------------------------------------
    # Geração Rápida de PDF
    # ------------------------------------------------------------------
    def _baixar_pdf(self, chave: str, pasta_dest: str, nome_base: str, xml_bytes: bytes = b"",
                    is_cancel_externo: bool = False):
        """Redireciona diretamente para a geração local, sem atrasos de rede."""
        if xml_bytes:
            return self._gerar_pdf_do_xml(xml_bytes, pasta_dest, nome_base, is_cancel_externo)
        return None

    def _gerar_pdf_do_xml(self, xml_bytes: bytes, pasta_dest: str, nome_base: str, is_cancel_externo: bool = False):
        return self._gerar_pdf_e_extrair_dados(xml_bytes, pasta_dest, nome_base, is_cancel_externo)

    # ------------------------------------------------------------------
    # Formatação (auxiliares do DANFSe)
    # ------------------------------------------------------------------
    def _fmt_data_br(self, iso):
        if not iso: return ""
        try:
            return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            return iso

    def _fmt_data_hora_br(self, iso):
        if not iso: return ""
        bruto = iso[:19].replace("T", " ")
        try:
            return datetime.strptime(bruto, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M:%S")
        except Exception:
            return bruto

    def _fmt_doc(self, doc):
        doc = re.sub(r'\D', '', doc or '')
        if len(doc) == 14:
            return f"{doc[0:2]}.{doc[2:5]}.{doc[5:8]}/{doc[8:12]}-{doc[12:14]}"
        if len(doc) == 11:
            return f"{doc[0:3]}.{doc[3:6]}.{doc[6:9]}-{doc[9:11]}"
        return doc or "-"

    def _fmt_cep(self, cep):
        cep = re.sub(r'\D', '', cep or '')
        return f"{cep[:5]}-{cep[5:]}" if len(cep) == 8 else (cep or "-")

    def _fmt_money(self, v):
        try:
            return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "R$ 0,00"

    def _gerar_qrcode_reader(self, chave):
        try:
            import qrcode
            url = f"https://www.nfse.gov.br/ConsultaPublica/?tpc=1&chave={chave}"
            qr = qrcode.QRCode(border=1, box_size=6, error_correction=qrcode.constants.ERROR_CORRECT_M)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return buf
        except Exception:
            return None

    def _gerar_pdf_e_extrair_dados(self, xml_bytes: bytes, pasta_dest: str, nome_base: str,
                                   is_cancel_externo: bool = False):
        """
        Gera DANFSe local fiel ao leiaute oficial do Portal Nacional da NFS-e (NT-008/SE-CGNFS-e).
        """
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib import colors
            from reportlab.lib.styles import ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
            from reportlab.lib.units import mm
            import xml.etree.ElementTree as ET
        except ImportError:
            self._log("    ℹ️ reportlab não instalado. Execute: pip install reportlab", "info")
            return None

        try:
            xml_str = xml_bytes.decode("utf-8", errors="ignore")

            def strip_ns(s):
                s = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', s)
                s = re.sub(r'<(/?)(?:\w[\w.-]*:)', r'<\1', s)
                return s

            xml_clean = strip_ns(xml_str)
            root = ET.fromstring(xml_clean)

            def get_path(path, default=""):
                el = root.find(".//" + path)
                return (el.text or "").strip() if el is not None else default

            def existe(path):
                return root.find(".//" + path) is not None

            def get_tag(tag, default=""):
                tl = tag.lower()
                for el in root.iter():
                    if el.tag.lower() == tl:
                        return (el.text or "").strip()
                return default

            def get_float_list(tags, default=0.0):
                for tag in tags:
                    v = get_tag(tag)
                    if v:
                        try:
                            return float(v.replace(",", "."))
                        except Exception:
                            pass
                return default

            def d(v):
                return v.strip() if isinstance(v, str) and v.strip() else "-"

            def fmt_cod(cod):
                cod = re.sub(r'\D', '', cod or '')
                return f"{cod[0:2]}.{cod[2:4]}.{cod[4:6]}" if len(cod) == 6 else (cod or "-")

            # ------------------------------------------------------------------
            # IDENTIFICAÇÃO
            # ------------------------------------------------------------------
            numero = get_tag("nNFSe") or get_tag("nDPS") or "?"
            n_dps = get_tag("nDPS") or ""
            serie_dps = get_tag("serie") or ""
            dt_compet = self._fmt_data_br(get_tag("dCompet"))
            dt_emi = self._fmt_data_hora_br(get_tag("dhProc") or get_tag("dhEmi"))
            dt_emi_dps = self._fmt_data_hora_br(get_tag("dhEmi")) or dt_emi

            chave_ac = ""
            el_inf = root.find(".//infNFSe")
            if el_inf is not None: chave_ac = el_inf.get("Id", "").replace("NFS", "")

            m_cstat = re.search(r'<(?:\w+:)?cStat>\s*(\d+)\s*</(?:\w+:)?cStat>', xml_str)
            c_stat = m_cstat.group(1) if m_cstat else ""
            is_cancel = is_cancel_externo or (c_stat in ("101", "102", "111", "112", "151", "152"))
            is_subst = c_stat == "103"

            # ------------------------------------------------------------------
            # PRESTADOR / EMITENTE
            # ------------------------------------------------------------------
            p_cnpj = get_path("emit/CNPJ") or get_path("prest/CNPJ")
            p_cpf = get_path("emit/CPF") or get_path("prest/CPF")
            p_doc = self._fmt_doc(p_cnpj or p_cpf)
            p_im = d(get_path("emit/IM") or get_path("prest/IM"))
            p_fone = d(get_path("emit/fone") or get_path("prest/fone"))
            p_nome = get_path("emit/xNome") or get_path("prest/xNome") or get_tag("xNome")
            p_email = d(get_path("emit/email") or get_path("prest/email"))
            p_lgr = get_path("emit/enderNac/xLgr") or get_path("prest/end/xLgr")
            p_nro = get_path("emit/enderNac/nro") or get_path("prest/end/nro")
            p_cpl = get_path("emit/enderNac/xCpl") or get_path("prest/end/xCpl")
            p_bai = get_path("emit/enderNac/xBairro") or get_path("prest/end/xBairro")
            p_uf = get_path("emit/enderNac/UF") or get_path("prest/end/endNac/UF")
            p_cep = get_path("emit/enderNac/CEP") or get_path("prest/end/endNac/CEP")
            p_cod_mun = get_path("emit/enderNac/cMun") or get_path("prest/end/endNac/cMun")
            p_mun_uf = self._municipio_uf(p_cod_mun, get_tag("xLocEmi"), p_uf)
            p_end = d(", ".join([x for x in [p_lgr, p_nro] if x]) + (f" - {p_cpl}" if p_cpl else "") + (f" - {p_bai}" if p_bai else ""))
            p_ibge_cep = f"{d(p_cod_mun)} / {self._fmt_cep(p_cep)}"

            tp_emit_map = {"1": "Prestador do Serviço", "2": "Órgão Público Emitente", "3": "Sistema do Contribuinte"}
            tp_emit_txt = tp_emit_map.get(get_tag("tpEmit"), "-")

            opsimp_map = {"1": "Não Optante", "2": "Optante - Microempreendedor Individual (MEI)", "3": "Optante"}
            op_simp_nac = get_path("prest/regTrib/opSimpNac")
            p_simples = opsimp_map.get(op_simp_nac, "-")

            regapur_map = {
                "1": "Regime de apuração dos tributos federais e municipal pelo SN",
                "2": "Regime de apuração dos tributos federais pelo SN e do ISSQN pelo regime normal",
                "3": "Regime de apuração dos tributos federais e municipal pelo regime normal",
            }
            p_regime_apur = regapur_map.get(get_path("prest/regTrib/regApTribSN"), "-") if op_simp_nac != "1" else "-"

            regesp_map = {
                "0": "Nenhum", "1": "Estimativa", "2": "Sociedade de Profissionais", "3": "Cooperativa",
                "4": "Microempreendedor Individual (MEI)", "5": "Microempresa ou Empresa de Pequeno Porte (ME/EPP)",
                "6": "Regime Especial Municipal", "9": "Outro",
            }
            p_regime_especial = regesp_map.get(get_path("prest/regTrib/regEspTrib"), "-")

            # ------------------------------------------------------------------
            # TOMADOR
            # ------------------------------------------------------------------
            tem_tomador = existe("toma")
            t_cnpj = get_path("toma/CNPJ")
            t_cpf = get_path("toma/CPF")
            t_doc = self._fmt_doc(t_cnpj or t_cpf)
            t_im = d(get_path("toma/IM"))
            t_fone = d(get_path("toma/fone"))
            t_nome = get_path("toma/xNome")
            t_email = d(get_path("toma/email"))
            t_lgr = get_path("toma/end/xLgr")
            t_nro = get_path("toma/end/nro")
            t_bai = get_path("toma/end/xBairro")
            t_cod_mun = get_path("toma/end/endNac/cMun")
            t_cep = get_path("toma/end/endNac/CEP")
            t_mun_uf = self._municipio_uf(t_cod_mun)
            t_end = d(", ".join([x for x in [t_lgr, t_nro] if x]) + (f" - {t_bai}" if t_bai else ""))
            t_ibge_cep = f"{d(t_cod_mun)} / {self._fmt_cep(t_cep)}"

            # ------------------------------------------------------------------
            # INTERMEDIÁRIO
            # ------------------------------------------------------------------
            tem_interm = existe("interm")
            if tem_interm:
                i_cnpj = self._fmt_doc(get_path("interm/CNPJ") or get_path("interm/CPF"))
                i_im = d(get_path("interm/IM"))
                i_fone = d(get_path("interm/fone"))
                i_nome = get_path("interm/xNome")
                i_email = d(get_path("interm/email"))
                i_lgr = get_path("interm/end/xLgr")
                i_nro = get_path("interm/end/nro")
                i_bai = get_path("interm/end/xBairro")
                i_cod_mun = get_path("interm/end/endNac/cMun")
                i_cep = get_path("interm/end/endNac/CEP")
                i_mun_uf = self._municipio_uf(i_cod_mun)
                i_end = d(", ".join([x for x in [i_lgr, i_nro] if x]) + (f" - {i_bai}" if i_bai else ""))
                i_ibge_cep = f"{d(i_cod_mun)} / {self._fmt_cep(i_cep)}"

            # ------------------------------------------------------------------
            # SERVIÇO PRESTADO
            # ------------------------------------------------------------------
            desc_serv = get_tag("xDescServ") or "-"
            cod_trib_nac = get_tag("cTribNac")
            x_trib_nac = get_tag("xTribNac")
            trib_nac_txt = f"{fmt_cod(cod_trib_nac)} - {x_trib_nac}" if x_trib_nac else fmt_cod(cod_trib_nac)
            cod_trib_mun = get_tag("cTribMun")
            x_trib_mun_raw = get_tag("xTribMun")
            x_trib_mun = x_trib_mun_raw if x_trib_mun_raw and x_trib_mun_raw != x_trib_nac else ""
            trib_mun_txt = f"{cod_trib_mun} - {x_trib_mun}" if cod_trib_mun else "-"
            cod_nbs = get_tag("cNBS") or "-"
            cod_loc_prest = get_tag("cLocPrestacao")
            loc_prest_uf = self._municipio_uf(cod_loc_prest, get_tag("xLocPrestacao"), p_uf)
            pais_prest = get_tag("cPaisPrestacao") or "-"

            # ------------------------------------------------------------------
            # VALORES
            # ------------------------------------------------------------------
            v_bc = get_float_list(["vBC"])
            aliq_iss = get_float_list(["pAliqAplic", "pAliq"])
            v_iss = get_float_list(["vISSQN"])
            v_liq = get_float_list(["vLiq"])
            v_serv = get_float_list(["vServ"])
            if v_serv == 0.0: v_serv = v_bc
            v_desc = get_float_list(["vDescIncond", "vDesc"])
            v_desc_c = get_float_list(["vDescCond"])
            v_ded = get_float_list(["vDedRed"])
            v_calc_bm = get_float_list(["vCalcBM", "vRedBCBM"])

            tp_bm_map = {"1": "Isenção", "2": "Redução de Base de Cálculo", "3": "Redução de Alíquota",
                        "4": "Redução do Valor a Recolher"}
            bm_txt = tp_bm_map.get(get_tag("tpBM"), "-")

            trib_issqn_map = {"1": "Operação Tributável", "2": "Imunidade", "3": "Exportação de Serviço",
                              "4": "Não Incidência"}
            existe_trib_mun = existe("valores/trib/tribMun")
            trib_issqn_txt = trib_issqn_map.get(get_path("valores/trib/tribMun/tribISSQN"),
                                                "Operação Tributável" if (v_iss or v_bc) else "-")

            mun_incid_uf = self._municipio_uf(get_tag("cLocIncid"), get_tag("xLocIncid"), p_uf)
            pais_result = "Brasil"

            tp_imunidade_map = {
                "1": "Livros, jornais, periódicos e o papel destinado à sua impressão",
                "2": "Fonogramas e videofonogramas musicais",
                "3": "Templos de qualquer culto",
                "4": "Patrimônio, renda ou serviços da União, Estados e Municípios",
                "5": "Patrimônio, renda ou serviços de partidos políticos, entidades sindicais, "
                     "instituições de educação e assistência social sem fins lucrativos",
            }
            imunidade_txt = tp_imunidade_map.get(get_tag("tpImunidade"), "-")

            tp_susp_map = {"1": "Exigibilidade Suspensa por Decisão Judicial",
                          "2": "Exigibilidade Suspensa por Processo Administrativo"}
            susp_txt = tp_susp_map.get(get_tag("tpSusp"), "Não")
            n_processo = d(get_tag("nProcesso"))

            tp_ret_issqn = get_path("valores/trib/tribMun/tpRetISSQN") or "1"
            iss_retido = tp_ret_issqn in ("2", "3")
            ret_iss_txt = {"1": "Não Retido", "2": "Retido pelo Tomador",
                          "3": "Retido pelo Intermediário"}.get(tp_ret_issqn, "Não Retido")

            if v_iss == 0.0 and aliq_iss > 0 and v_serv > 0:
                v_iss = round(max(v_serv - v_desc - v_ded, 0) * aliq_iss / 100, 2)

            # Federais
            v_inss = get_float_list(["vRetCP"])
            v_irrf = get_float_list(["vRetIRRF"])
            v_csll = get_float_list(["vRetCSLL"])

            tp_ret_pisc = get_path("valores/trib/tribFed/piscofins/tpRetPisCofins") or "2"
            pis_retido_map = {"1": True, "2": False, "3": True, "4": True, "5": True,
                              "6": False, "7": False, "8": False, "9": True}
            cofins_retido_map = {"1": True, "2": False, "3": True, "4": True, "5": False,
                                 "6": True, "7": True, "8": False, "9": False}
            pis_retido = pis_retido_map.get(tp_ret_pisc, tp_ret_pisc not in ("0", "2"))
            cofins_retido = cofins_retido_map.get(tp_ret_pisc, tp_ret_pisc not in ("0", "2"))
            ret_piscofins_map = {
                "0": "PIS/COFINS/CSLL Não Retidos", "1": "PIS/COFINS Retidos", "2": "PIS/COFINS Não Retidos",
                "3": "PIS/COFINS/CSLL Retidos", "4": "PIS/COFINS Retidos, CSLL Não Retido",
                "5": "PIS Retido, COFINS/CSLL Não Retidos", "6": "COFINS Retido, PIS/CSLL Não Retidos",
                "7": "PIS Não Retido, COFINS/CSLL Retidos", "8": "PIS/COFINS Não Retidos, CSLL Retido",
                "9": "COFINS Não Retido, PIS/CSLL Retidos",
            }
            ret_piscofins_txt = f"{tp_ret_pisc} - {ret_piscofins_map.get(tp_ret_pisc, 'PIS/COFINS Não Retidos')}"

            v_pis = get_float_list(["vPis"])
            v_cofins = get_float_list(["vCofins"])
            v_pis_ret = v_pis if pis_retido else 0.0
            v_cofins_ret = v_cofins if cofins_retido else 0.0
            v_piscofins_proprio = round((0.0 if pis_retido else v_pis) + (0.0 if cofins_retido else v_cofins), 2)

            v_total_retencoes = round(v_inss + v_irrf + v_csll + v_pis_ret + v_cofins_ret, 2)

            if v_liq == 0.0:
                ret_iss_val = v_iss if iss_retido else 0
                v_liq = round(v_serv - v_desc - v_desc_c - v_ded - ret_iss_val - v_total_retencoes, 2)

            v_tot_trib_fed = get_float_list(["vTotTribFed"])
            v_tot_trib_est = get_float_list(["vTotTribEst"])
            v_tot_trib_mun = get_float_list(["vTotTribMun"])

            tp_emis = get_tag("tpEmis")
            inf_cont = get_tag("xInfComp") or ("Nota emitida via DPS" if tp_emis == "2" else "")
            partes_compl = [p for p in [f"NBS: {cod_nbs}" if cod_nbs != "-" else "",
                                        f"Inf Cont: {inf_cont}" if inf_cont else ""] if p]
            txt_compl_1 = " | ".join(partes_compl)
            txt_compl_2 = (f"Totais Aproximados dos Tributos cfe. Lei nº 12.741/2012: "
                          f"Federais: {self._fmt_money(v_tot_trib_fed)}; "
                          f"Estaduais: {self._fmt_money(v_tot_trib_est)}; "
                          f"Municipais: {self._fmt_money(v_tot_trib_mun)}")

            # -------------------------------------------------------------------------
            # CONSTRUÇÃO DO PDF NO PADRÃO OFICIAL
            # -------------------------------------------------------------------------
            caminho_pdf = os.path.join(pasta_dest, nome_base + ".pdf")
            doc = SimpleDocTemplate(caminho_pdf, pagesize=A4, leftMargin=8 * mm, rightMargin=8 * mm,
                                    topMargin=6 * mm, bottomMargin=6 * mm)

            sty_lbl = ParagraphStyle("lbl", fontName="Helvetica-Bold", fontSize=6, leading=7)
            sty_val = ParagraphStyle("val", fontName="Helvetica", fontSize=7, leading=8.5)
            sty_val_c = ParagraphStyle("valc", fontName="Helvetica-Bold", fontSize=7.5, leading=9, alignment=1)
            sty_sec = ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.black,
                                     alignment=1)
            sty_h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=12, textColor=colors.black, alignment=1)
            sty_h1b = ParagraphStyle("h1b", fontName="Helvetica", fontSize=9, textColor=colors.black, alignment=1)
            sty_hr1 = ParagraphStyle("hr1", fontName="Helvetica-Bold", fontSize=8, alignment=2)
            sty_hr2 = ParagraphStyle("hr2", fontName="Helvetica", fontSize=6, alignment=2, textColor=colors.HexColor("#444444"))
            sty_qrcap = ParagraphStyle("qrcap", fontName="Helvetica", fontSize=6, leading=7)
            sty_chave = ParagraphStyle("chave", fontName="Helvetica", fontSize=9, leading=11)

            def c(lbl, val):
                return Table([
                    [Paragraph(lbl, sty_lbl)],
                    [Paragraph(str(val), sty_val)]
                ], colWidths=["*"], style=TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 2),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                    ('TOPPADDING', (0, 0), (-1, -1), 1),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                ]))

            def draw_box(cells, widths, shade_last=False):
                estilo = [
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('TOPPADDING', (0, 0), (-1, -1), 1.2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 1.2),
                    ('LEFTPADDING', (0, 0), (-1, -1), 2),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ]
                if shade_last:
                    estilo.append(('BACKGROUND', (-1, 0), (-1, -1), colors.HexColor("#EAEAEA")))
                return Table([cells], colWidths=widths, style=TableStyle(estilo))

            def draw_title(title):
                return Table([[Paragraph(title, sty_sec)]], colWidths=[190 * mm], style=TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#EAEAEA")),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('TOPPADDING', (0, 0), (-1, -1), 1.5),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
                ]))

            def linha_aviso(texto):
                return draw_box([Paragraph(texto, sty_val_c)], [190 * mm])

            def fmt(v):
                return self._fmt_money(v)

            def sp():
                return Spacer(1, 1 * mm)

            story = []

            # --------------------------------------------------------------
            # CABEÇALHO
            # --------------------------------------------------------------
            try:
                logo_path = self.parent.resource_path("nfse_logo.png")
                logo_cell = RLImage(logo_path, width=36 * mm, height=7.3 * mm)
            except Exception:
                logo_cell = Paragraph("<b>NFSe</b>", sty_h1)

            texto_ambiente = "NFS-e SEM VALIDADE JURÍDICA" if (get_tag("tpAmb") == "2") else ""
            titulo_central = [Paragraph("DANFSe v1.0", sty_h1), Paragraph("Documento Auxiliar da NFS-e", sty_h1b)]
            if texto_ambiente:
                titulo_central.append(Paragraph(f"<font color='red'><b>{texto_ambiente}</b></font>", sty_h1b))

            t_head = Table([[
                logo_cell,
                titulo_central,
                [Paragraph(p_mun_uf.replace(" - ", " / "), sty_hr1),
                 Paragraph("PRODUÇÃO" if get_tag("tpAmb") != "2" else "HOMOLOGAÇÃO", sty_hr2)],
            ]], colWidths=[45 * mm, 100 * mm, 45 * mm], style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (1, 0), (1, 0), 'CENTER'),
                ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ]))
            story.append(t_head)
            story.append(Spacer(1, 1.5 * mm))

            # --------------------------------------------------------------
            # CHAVE DE ACESSO + QR CODE
            # --------------------------------------------------------------
            qr_reader = self._gerar_qrcode_reader(chave_ac) if chave_ac else None
            qr_cell = RLImage(qr_reader, width=18 * mm, height=18 * mm) if qr_reader else Paragraph("[ QR CODE ]", sty_qrcap)
            qr_caption = Paragraph(
                "A autenticidade desta NFS-e pode ser verificada pela leitura deste código QR "
                "ou pela consulta da chave de acesso no portal nacional da NFS-e", sty_qrcap)

            story.append(draw_title("CHAVE DE ACESSO DA NFS-E"))
            story.append(draw_box([Paragraph(chave_ac, sty_chave), qr_cell, qr_caption],
                                  [110 * mm, 20 * mm, 60 * mm]))
            story.append(sp())

            # IDENTIFICAÇÃO
            story.append(draw_box([
                c("Número da NFS-e", numero), c("Competência da NFS-e", dt_compet),
                c("Data e Hora da emissão da NFS-e", dt_emi)
            ], [63.3 * mm, 63.3 * mm, 63.4 * mm]))
            story.append(draw_box([
                c("Número da DPS", n_dps), c("Série da DPS", serie_dps),
                c("Data e Hora da emissão da DPS", dt_emi_dps)
            ], [63.3 * mm, 63.3 * mm, 63.4 * mm]))
            story.append(sp())

            # --------------------------------------------------------------
            # EMITENTE DA NFS-e / PRESTADOR DO SERVIÇO
            # --------------------------------------------------------------
            story.append(draw_title("EMITENTE DA NFS-E"))
            story.append(draw_box([Paragraph(tp_emit_txt, sty_val)], [190 * mm]))
            story.append(draw_box([c("CNPJ / CPF / NIF", p_doc), c("Inscrição Municipal", p_im), c("Telefone", p_fone)],
                                  [63.3 * mm, 63.3 * mm, 63.4 * mm]))
            story.append(draw_box([c("Nome / Nome Empresarial", p_nome), c("Município / UF", p_mun_uf),
                                   c("Código IBGE / CEP", p_ibge_cep)], [76 * mm, 57 * mm, 57 * mm]))
            story.append(draw_box([c("Endereço", p_end), c("E-mail", p_email)], [95 * mm, 95 * mm]))
            story.append(draw_box([c("Simples Nacional na Data de Competência", p_simples),
                                   c("Regime de Apuração Tributária pelo SN", p_regime_apur)],
                                  [63.3 * mm, 126.7 * mm]))
            story.append(sp())

            # --------------------------------------------------------------
            # TOMADOR DO SERVIÇO
            # --------------------------------------------------------------
            story.append(draw_title("TOMADOR DO SERVIÇO"))
            if tem_tomador:
                story.append(draw_box([c("CNPJ / CPF / NIF", t_doc), c("Inscrição Municipal", t_im), c("Telefone", t_fone)],
                                      [63.3 * mm, 63.3 * mm, 63.4 * mm]))
                story.append(draw_box([c("Nome / Nome Empresarial", d(t_nome)), c("Município / UF", t_mun_uf),
                                       c("Código IBGE / CEP", t_ibge_cep)], [76 * mm, 57 * mm, 57 * mm]))
                story.append(draw_box([c("Endereço", t_end), c("E-mail", t_email)], [95 * mm, 95 * mm]))
            else:
                story.append(linha_aviso("TOMADOR/ADQUIRENTE DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e"))
            story.append(sp())

            # --------------------------------------------------------------
            # INTERMEDIÁRIO DA OPERAÇÃO
            # --------------------------------------------------------------
            story.append(draw_title("INTERMEDIÁRIO DA OPERAÇÃO"))
            if tem_interm:
                story.append(draw_box([c("CNPJ / CPF / NIF", i_cnpj), c("Inscrição Municipal", i_im), c("Telefone", i_fone)],
                                      [63.3 * mm, 63.3 * mm, 63.4 * mm]))
                story.append(draw_box([c("Nome / Nome Empresarial", d(i_nome)), c("Município / UF", i_mun_uf),
                                       c("Código IBGE / CEP", i_ibge_cep)], [76 * mm, 57 * mm, 57 * mm]))
                story.append(draw_box([c("Endereço", i_end), c("E-mail", i_email)], [95 * mm, 95 * mm]))
            else:
                story.append(linha_aviso("INTERMEDIÁRIO DO SERVIÇO NÃO IDENTIFICADO NA NFS-e"))
            story.append(sp())

            # --------------------------------------------------------------
            # SERVIÇO PRESTADO
            # --------------------------------------------------------------
            story.append(draw_title("SERVIÇO PRESTADO"))
            story.append(draw_box([
                c("Código de Tributação Nacional", trib_nac_txt), c("Código de Tributação Municipal", trib_mun_txt),
                c("Local da Prestação", loc_prest_uf), c("País da Prestação", pais_prest)
            ], [65 * mm, 40 * mm, 55 * mm, 30 * mm]))
            story.append(draw_box([c("Descrição do Serviço", desc_serv)], [190 * mm]))
            story.append(sp())

            # --------------------------------------------------------------
            # TRIBUTAÇÃO MUNICIPAL (ISSQN)
            # --------------------------------------------------------------
            story.append(draw_title("TRIBUTAÇÃO MUNICIPAL (ISSQN)"))
            if existe_trib_mun or v_bc or v_iss:
                story.append(draw_box([
                    c("Tributação do ISSQN", trib_issqn_txt), c("Município / UF de Incidência do ISSQN", mun_incid_uf),
                    c("País Resultado da Prestação do Serviço", pais_result)
                ], [50 * mm, 90 * mm, 50 * mm]))
                story.append(draw_box([
                    c("Regime Especial de Tributação", p_regime_especial), c("Tipo de Imunidade", imunidade_txt),
                    c("Suspensão da Exigibilidade do ISSQN", susp_txt), c("Número Processo Suspensão", n_processo)
                ], [47.5 * mm, 47.5 * mm, 47.5 * mm, 47.5 * mm]))
                story.append(draw_box([
                    c("Benefício Municipal", bm_txt), c("Cálculo do BM", fmt(v_calc_bm)),
                    c("Total Deduções/Reduções", fmt(v_ded)), c("Desconto Incondicionado", fmt(v_desc))
                ], [47.5 * mm, 47.5 * mm, 47.5 * mm, 47.5 * mm]))
                story.append(draw_box([
                    c("Valor do Serviço", fmt(v_serv)), c("BC ISSQN", fmt(v_bc)),
                    c("Alíquota Aplicada", f"{aliq_iss:.2f}".replace(".", ",") + "%"), c("ISSQN Apurado", fmt(v_iss))
                ], [47.5 * mm, 47.5 * mm, 47.5 * mm, 47.5 * mm]))
                story.append(draw_box([c("Retenção do ISSQN", ret_iss_txt)], [190 * mm]))
            else:
                story.append(linha_aviso("TRIBUTAÇÃO MUNICIPAL (ISSQN) - OPERAÇÃO NÃO SUJEITA AO ISSQN"))
            story.append(sp())

            # --------------------------------------------------------------
            # TRIBUTAÇÃO FEDERAL (EXCETO CBS)
            # --------------------------------------------------------------
            story.append(draw_title("TRIBUTAÇÃO FEDERAL (EXCETO CBS)"))
            story.append(draw_box([
                c("IRRF", fmt(v_irrf)), c("Contribuição Previdenciária - Retida", fmt(v_inss)),
                c("Contribuições Sociais - Retidas (CSLL)", fmt(v_csll)),
            ], [63.3 * mm, 63.3 * mm, 63.4 * mm]))
            pis_lbl = "PIS - Retido" if pis_retido else "PIS - Débito Apuração Própria"
            cofins_lbl = "COFINS - Retida" if cofins_retido else "COFINS - Débito Apuração Própria"
            story.append(draw_box([
                c(pis_lbl, fmt(v_pis)), c(cofins_lbl, fmt(v_cofins)),
                c("Descrição Contrib. Sociais - Retidas", ret_piscofins_txt),
            ], [50 * mm, 50 * mm, 90 * mm]))
            story.append(sp())

            # --------------------------------------------------------------
            # VALOR TOTAL DA NFS-E
            # --------------------------------------------------------------
            story.append(draw_title("VALOR TOTAL DA NFS-E"))
            story.append(draw_box([
                c("Valor do Serviço", fmt(v_serv)), c("Desconto Condicionado", fmt(v_desc_c)),
                c("Desconto Incondicionado", fmt(v_desc)),
            ], [63.3 * mm, 63.3 * mm, 63.4 * mm]))
            total_ret_geral = round(v_total_retencoes + (v_iss if iss_retido else 0), 2)
            story.append(draw_box([
                c("Total das Retenções (ISSQN / Federais)", fmt(total_ret_geral)),
                c("Valor Líquido da NFS-e", fmt(v_liq)),
            ], [95 * mm, 95 * mm], shade_last=True))
            story.append(sp())

            # --------------------------------------------------------------
            # INFORMAÇÕES COMPLEMENTARES
            # --------------------------------------------------------------
            story.append(draw_title("INFORMAÇÕES COMPLEMENTARES"))
            texto_final = " | ".join([p for p in [txt_compl_1, txt_compl_2] if p])
            story.append(draw_box([Paragraph(texto_final, sty_val)], [190 * mm]))

            def marca_dagua(canvas_obj, _doc):
                if not (is_cancel or is_subst):
                    return
                texto = "CANCELADA" if is_cancel else "SUBSTITUÍDA"
                canvas_obj.saveState()
                canvas_obj.setFont("Helvetica-Bold", 60)
                canvas_obj.setFillColor(colors.Color(0.5, 0.5, 0.5, alpha=0.35))
                canvas_obj.translate(A4[0] / 2, A4[1] / 2)
                canvas_obj.rotate(45)
                canvas_obj.drawCentredString(0, 0, texto)
                canvas_obj.restoreState()

            doc.build(story, onFirstPage=marca_dagua, onLaterPages=marca_dagua)
            self._log(f"    📄 DANFSe Local: NFS-e nº {numero} ({nome_base}.pdf)" + (" [CANCELADA]" if is_cancel else ""), "sucesso")
            self.parent.estatisticas.registrar_evento("nota_baixada")

            # Retorna o dicionário com os dados fiscais para o Excel
            return {
                "NFS-e": numero,
                "Competência": dt_compet,
                "Data Emissão": dt_emi,
                "Status": "CANCELADA" if is_cancel else "ATIVA",
                "Prestador CNPJ": p_doc,
                "Prestador Nome": p_nome,
                "Tomador CNPJ/CPF": t_doc,
                "Tomador Nome": t_nome,
                "Valor Serviço": v_serv,
                "BC ISSQN": v_bc,
                "Alíquota ISS": aliq_iss,
                "ISS Retido": "Sim" if iss_retido else "Não",
                "ISS": v_iss,
                "INSS (CP)": v_inss,
                "IRRF": v_irrf,
                "CSLL": v_csll,
                "PIS": v_pis_ret,
                "COFINS": v_cofins_ret,
                "PIS/COFINS Próprio": v_piscofins_proprio,
                "Total Retenções Federais": v_total_retencoes,
                "Desconto": v_desc,
                "Valor Líquido": v_liq,
                "Chave": chave_ac,
            }

        except Exception as e:
            self._log(f"    ⚠️ Falha ao gerar DANFSe Local: {e}", "erro")
            return None

    def _salvar_nsu(self, pasta_base, cnpj, tipo, nsu):
        arquivos = []
        if tipo in ("emitidas", "ambas"): arquivos.append(os.path.join(pasta_base, f"_nsu_{cnpj}_emitidas.txt"))
        if tipo in ("tomadas", "ambas"): arquivos.append(os.path.join(pasta_base, f"_nsu_{cnpj}_tomadas.txt"))
        for arq in arquivos:
            with open(arq, "w") as f: f.write(str(nsu))

    def _decodificar_conteudo(self, conteudo: bytes) -> bytes:
        try:
            decoded = base64.b64decode(conteudo)
            try:
                return gzip.decompress(decoded)
            except Exception:
                return decoded
        except Exception:
            return conteudo

    def _log(self, msg, tipo="info", divisor=False):
        self.parent.root.after(0, lambda: self.parent.log_msg(msg, tipo, divisor))