import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import os
import re
import shutil
import threading
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime

import pdfplumber
from utils import isolar_scroll_mouse


class LivroEletronicoModulo:
    """
    Compara as NFS-e TOMADAS já baixadas (XML/PDF) com o relatório de declaração
    de serviços tomados do Livro Eletrônico (Betha), localiza as notas que ainda
    não constam no livro e gera o arquivo-texto (leiaute oficial) para importação.

    Leiaute seguido: "Layout do arquivo para importação de declarações" (Betha
    Livro Eletrônico) — registros 1 (Declaração), 2 (Documentos) e 3 (Serviços).
    """

    CODIGOS_CANCELAMENTO = ("101", "102", "111", "112", "151", "152")

    MESES_PT = {
        1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
        5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
        9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO",
    }

    _RE_HEADER = re.compile(
        r'^\s*\d+\s+\d+\s+(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\s+(.*?)\s+(\d{2}/\d{2}/\d{4})\s+'
        r'(Nota fiscal|Cupom fiscal|Recibo|Outros)\s+\S+\s+(?:Ativo|Inativo|Cancelado)\s+'
        r'(\d+)(?:\s+(\d+))?\s+\S+\s*$'
    )
    _RE_CONTRIBUINTE = re.compile(r'Contribuinte:\s*(.+?)\s*\((\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\)')
    _RE_MUNICIPIO = re.compile(r'MUNIC[IÍ]PIO DE (.+)')
    _RE_SERVICO_DADO = re.compile(
        r'^\s*(\d{2}\.\d{4})\s+(.*?)\s{2,}([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$'
    )

    def __init__(self, parent):
        self.parent = parent

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def tela_livro(self):
        self.parent.limpar_tela()

        f_header = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_header.pack(pady=5, fill="x")
        ctk.CTkLabel(f_header, text="📕 Livro Eletrônico — Notas Ausentes",
                     font=("Arial", 20, "bold"), text_color="#8e44ad").pack(pady=5)
        ctk.CTkLabel(f_header,
                     text="Compara as NFS-e tomadas já baixadas com o relatório do Livro\n"
                          "e gera o arquivo-texto de importação (apenas serviços tomados)",
                     font=("Arial", 12), text_color="gray").pack()

        f_cfg = ctk.CTkFrame(self.parent.container)
        f_cfg.pack(fill="x", padx=40, pady=8)
        ctk.CTkLabel(f_cfg, text="CONFIGURAÇÃO", font=("Arial", 11, "bold"),
                     text_color="#8e44ad").pack(pady=4)

        f_pasta = ctk.CTkFrame(f_cfg, fg_color="transparent")
        f_pasta.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(f_pasta, text="Pasta das Notas:", font=("Arial", 12, "bold"),
                     width=170, anchor="w").pack(side="left")
        self.ent_pasta = ctk.CTkEntry(f_pasta, width=340)
        self.ent_pasta.pack(side="left", padx=10)
        ctk.CTkButton(f_pasta, text="...", width=40,
                      command=self._selecionar_pasta).pack(side="left")

        f_pdf = ctk.CTkFrame(f_cfg, fg_color="transparent")
        f_pdf.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(f_pdf, text="PDF do Livro Eletrônico:", font=("Arial", 12, "bold"),
                     width=170, anchor="w").pack(side="left")
        self.ent_pdf = ctk.CTkEntry(f_pdf, width=340)
        self.ent_pdf.pack(side="left", padx=10)
        ctk.CTkButton(f_pdf, text="...", width=40,
                      command=self._selecionar_pdf).pack(side="left")

        f_pref = ctk.CTkFrame(f_cfg, fg_color="transparent")
        f_pref.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(f_pref, text="CNPJ da Prefeitura:", font=("Arial", 12, "bold"),
                     width=170, anchor="w").pack(side="left")
        self.ent_cnpj_pref = ctk.CTkEntry(f_pref, placeholder_text="Apenas números", width=200)
        self.ent_cnpj_pref.insert(0, self.parent.configuracoes.get("ultimo_cnpj_prefeitura_livro", ""))
        self.ent_cnpj_pref.pack(side="left", padx=10)

        f_log = ctk.CTkFrame(self.parent.container)
        f_log.pack(fill="both", expand=True, padx=40, pady=6)
        ctk.CTkLabel(f_log, text="Log:", font=("Arial", 11, "bold"),
                     text_color="gray").pack(anchor="w", padx=10, pady=2)
        self.parent.txt_log = scrolledtext.ScrolledText(
            f_log, height=16, state="disabled",
            bg="#1e1e1e", fg="white", font=("Consolas", 10))
        self.parent.txt_log.pack(fill="both", expand=True, padx=10, pady=4)
        isolar_scroll_mouse(self.parent.txt_log)

        f_btns = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_btns.pack(pady=10)

        ctk.CTkButton(f_btns, text="🔍 Comparar e Gerar Importação",
                      command=self._iniciar,
                      width=260, height=45, font=("Arial", 13, "bold"),
                      fg_color="#8e44ad", hover_color="#6c3483").pack(side="left", padx=6)

        ctk.CTkButton(f_btns, text="Voltar",
                      command=self.parent.mostrar_menu_inicial,
                      width=90, height=45, fg_color="gray").pack(side="left", padx=6)

    def _selecionar_pasta(self):
        p = filedialog.askdirectory()
        if p:
            self.ent_pasta.delete(0, tk.END)
            self.ent_pasta.insert(0, p)

    def _selecionar_pdf(self):
        p = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if p:
            self.ent_pdf.delete(0, tk.END)
            self.ent_pdf.insert(0, p)

    def _iniciar(self):
        pasta = self.ent_pasta.get().strip()
        pdf_path = self.ent_pdf.get().strip()
        cnpj_pref = "".join(filter(str.isdigit, self.ent_cnpj_pref.get()))

        if not pasta or not os.path.isdir(pasta):
            messagebox.showwarning("Validação", "Selecione uma pasta de notas válida.")
            return
        if not pdf_path or not os.path.isfile(pdf_path):
            messagebox.showwarning("Validação", "Selecione o arquivo PDF do Livro Eletrônico.")
            return
        if len(cnpj_pref) != 14:
            messagebox.showwarning("Validação",
                                    "Informe o CNPJ da Prefeitura (14 dígitos) — o portal exige o "
                                    "registro '0' com esse dado no arquivo de importação.")
            return

        self.parent.salvar_config("ultimo_cnpj_prefeitura_livro", cnpj_pref)
        threading.Thread(target=self._executar, args=(pasta, pdf_path, cnpj_pref), daemon=True).start()

    def _log(self, msg, tipo="info", divisor=False):
        self.parent.root.after(0, lambda: self.parent.log_msg(msg, tipo, divisor))

    # ------------------------------------------------------------------
    # FLUXO PRINCIPAL
    # ------------------------------------------------------------------
    def _executar(self, pasta, pdf_path, cnpj_pref):
        try:
            self._log("Lendo relatório do Livro Eletrônico...", "info", divisor=True)
            (contribuinte_cnpj, contribuinte_nome, livro_set,
             total_livro, municipio_nome) = self._ler_livro_pdf(pdf_path)

            if not contribuinte_cnpj:
                self._log("❌ Não foi possível identificar o CNPJ do contribuinte no PDF. "
                           "Verifique se é o relatório correto do Livro Eletrônico.", "erro")
                return

            self._log(f"Contribuinte do livro: {contribuinte_nome or '?'} ({contribuinte_cnpj}) "
                       f"— Município: {municipio_nome or '?'}", "info")
            self._log(f"{total_livro} nota(s) já constam no livro.", "info")

            self._log("Lendo notas XML da pasta selecionada...", "info", divisor=True)
            xmls = []
            for raiz, dirs, arquivos in os.walk(pasta):
                if os.path.basename(raiz) == "Notas ausentes Livro":
                    dirs[:] = []  # não descer nas subpastas de competência já geradas
                    continue
                for arq in arquivos:
                    if arq.lower().endswith(".xml"):
                        xmls.append(os.path.join(raiz, arq))

            self._log(f"{len(xmls)} arquivo(s) XML encontrado(s) na pasta (busca recursiva).", "info")

            notas = []
            erros_leitura = 0
            for caminho_xml in xmls:
                try:
                    with open(caminho_xml, "rb") as f:
                        xml_bytes = f.read()
                    dados = self._parse_nota_xml(xml_bytes)
                    if not dados:
                        erros_leitura += 1
                        continue
                    dados["_caminho_xml"] = caminho_xml
                    notas.append(dados)
                except Exception as e:
                    erros_leitura += 1
                    self._log(f"  Erro lendo {os.path.basename(caminho_xml)}: {e}", "erro")

            if erros_leitura:
                self._log(f"{erros_leitura} arquivo(s) não puderam ser lidos/identificados (ignorados).", "info")

            # Mantém só as notas em que ESTA empresa é a TOMADORA (descarta emitidas
            # e descarta notas tomadas por outras empresas, caso a pasta seja compartilhada)
            antes = len(notas)
            notas = [n for n in notas if n["cnpj_prest"] != contribuinte_cnpj]
            descartadas_emitidas = antes - len(notas)
            if descartadas_emitidas:
                self._log(f"{descartadas_emitidas} arquivo(s) descartado(s) por serem NFS-e EMITIDAS "
                           f"pelo próprio contribuinte (não são serviço tomado).", "info")

            divergentes = [n for n in notas if n["cnpj_toma"] and n["cnpj_toma"] != contribuinte_cnpj]
            if divergentes:
                self._log(f"⚠️ {len(divergentes)} nota(s) na pasta pertencem a um TOMADOR diferente do "
                           f"contribuinte do livro ({contribuinte_cnpj}) e serão ignoradas.", "erro")
            notas = [n for n in notas if not n["cnpj_toma"] or n["cnpj_toma"] == contribuinte_cnpj]

            if not notas:
                self._log("Nenhuma nota tomada válida encontrada na pasta para este contribuinte.", "info")
                return

            # Município de referência do tomador (para localizado D/F)
            municipios_toma = {n["cmun_toma"] for n in notas if n.get("cmun_toma")}
            home_mun = next(iter(municipios_toma)) if municipios_toma else ""
            if len(municipios_toma) > 1:
                self._log(f"⚠️ Notas com mais de um código de município do tomador ({municipios_toma}); "
                           f"usando '{home_mun}' como referência para o campo 'localizado'.", "erro")

            def _chave(n):
                return (n["cnpj_prest"], self._f_data(n["d_compet"]), int(round(n["v_serv"] * 100)))

            # Counter: cada chave do livro só "cobre" uma nota da pasta. Se duas notas distintas
            # (nNFSe diferentes) tiverem CNPJ+data+valor idênticos por coincidência, a que sobrar
            # além do que o livro já tem aparece como ausente (processa em ordem de nNFSe p/
            # resultado determinístico).
            livro_restante = Counter(livro_set)
            ausentes = []
            for n in sorted(notas, key=lambda x: x["numero"]):
                chave = _chave(n)
                if livro_restante[chave] > 0:
                    livro_restante[chave] -= 1
                else:
                    ausentes.append(n)

            self._log(f"{len(ausentes)} nota(s) ausente(s) no livro (de {len(notas)} nota(s) tomada(s) lida(s)).",
                       "sucesso" if ausentes else "info", divisor=True)

            if not ausentes:
                self._log("Nenhuma nota ausente. Nada a fazer.", "info")
                return

            # Classificação D/F e natureza da operação
            for n in ausentes:
                n["localizado"] = "D" if n["c_loc_prest"] and n["c_loc_prest"] == home_mun else "F"
                trib = n.get("trib_issqn")
                if trib == "2":
                    n["natureza_operacao"] = "4"
                elif trib == "3":
                    n["natureza_operacao"] = "8"
                elif trib == "4":
                    n["natureza_operacao"] = "7"
                else:
                    n["natureza_operacao"] = "1" if n["localizado"] == "D" else "2"

            pasta_ausentes = os.path.join(pasta, "Notas ausentes Livro")
            os.makedirs(pasta_ausentes, exist_ok=True)

            # O portal do Livro Eletrônico só aceita um arquivo de importação por
            # competência. Agrupa as notas ausentes pela competência (dCompet) e
            # separa em uma subpasta por competência (ex.: nota emitida em 06 com
            # competência 05 vai para a subpasta "MAIO 2026").
            grupos = {}
            for n in ausentes:
                comp = self._competencia_pasta(n["d_compet"])
                grupos.setdefault(comp, []).append(n)

            self._log(f"Notas ausentes separadas em {len(grupos)} competência(s): "
                       f"{', '.join(sorted(grupos.keys()))}", "info")

            copiados = 0
            for comp_nome, notas_comp in sorted(grupos.items()):
                pasta_comp = os.path.join(pasta_ausentes, comp_nome)
                os.makedirs(pasta_comp, exist_ok=True)
                for n in notas_comp:
                    caminho_xml = n["_caminho_xml"]
                    base = os.path.splitext(os.path.basename(caminho_xml))[0]
                    pasta_origem = os.path.dirname(caminho_xml)
                    caminho_pdf = os.path.join(pasta_origem, base + ".pdf")

                    shutil.copy2(caminho_xml, os.path.join(pasta_comp, os.path.basename(caminho_xml)))
                    if os.path.exists(caminho_pdf):
                        shutil.copy2(caminho_pdf, os.path.join(pasta_comp, base + ".pdf"))
                    else:
                        self._log(f"  ⚠️ PDF não encontrado ao lado do XML: {base}", "erro")
                    copiados += 1
                    self._log(f"  📄 Ausente [{comp_nome}]: NFS-e nº {n['numero']} — "
                               f"{n['nome_prest']} ({n['cnpj_prest']})", "sucesso")

            self._log(f"{copiados} nota(s) copiada(s) para: {pasta_ausentes}", "sucesso")

            self._log("Gerando arquivo(s) de importação (.txt) por competência...", "info", divisor=True)
            for comp_nome, notas_comp in sorted(grupos.items()):
                pasta_comp = os.path.join(pasta_ausentes, comp_nome)
                sufixo_comp = re.sub(r'\W+', '_', comp_nome).strip('_')
                nome_txt = f"IMPORTACAO_LIVRO_TOMADOS_{sufixo_comp}_{datetime.now().strftime('%d%m%Y_%H%M')}.txt"
                caminho_txt = os.path.join(pasta_comp, nome_txt)
                tamanho_kb = self._gerar_arquivo_importacao(
                    notas_comp, cnpj_pref, contribuinte_cnpj, contribuinte_nome, caminho_txt)
                self._log(f"✅ Arquivo gerado [{comp_nome}]: {caminho_txt} ({tamanho_kb:.1f} KB)", "sucesso")
                if tamanho_kb > 480:
                    self._log(f"⚠️ Arquivo de {comp_nome} perto do limite de 512 KB do portal do Livro. "
                               "Pode ser necessário dividir em mais de um arquivo.", "erro")

            self._log("⚠️ Antes de importar: confira 'Optante Simples Nacional' e 'Natureza da operação' "
                       "(preenchidos por heurística a partir do XML) e valide o arquivo no próprio portal "
                       "do Livro Eletrônico antes do envio definitivo.", "erro")

        except Exception as e:
            self._log(f"Erro crítico: {e}", "erro")

    # ------------------------------------------------------------------
    # LEITURA DO PDF DO LIVRO
    # ------------------------------------------------------------------
    def _parse_valor_br(self, txt):
        try:
            return round(float(txt.replace(".", "").replace(",", ".")) * 100)
        except Exception:
            return None

    def _ler_livro_pdf(self, pdf_path):
        # NOTA: "Número inicial/final" deste relatório NÃO é o mesmo número que o "Nº Nota
        # Nacional" (nNFSe) do XML — são numerações diferentes dentro do Betha, e comparar por
        # número gera falsos "ausente" (duplicidade na importação). Por isso o cruzamento usa
        # CNPJ + data de emissão + valor do serviço, EXIGINDO OS TRÊS AO MESMO TEMPO. Usar só
        # CNPJ+valor (sem exigir a mesma data) causa falso "já no livro" quando o mesmo prestador
        # emite valores iguais/recorrentes em meses diferentes (comum em comissões), o que já
        # aconteceu na prática e zerou os "ausentes" indevidamente.
        #
        # É um Counter (multiconjunto), não um set: já aconteceu de duas notas REAIS e distintas
        # (nNFSe diferentes) terem CNPJ+data+valor idênticos por coincidência. Com um set as duas
        # bateriam contra a única entrada do livro e as duas sumiam; com Counter, cada entrada do
        # livro "consome" só uma ocorrência da pasta, e a nota excedente aparece como ausente.
        contribuinte_cnpj = None
        contribuinte_nome = None
        municipio_nome = None
        livro_set = Counter()
        total_notas = 0

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                texto = page.extract_text(layout=True) or ""

                if contribuinte_cnpj is None:
                    m = self._RE_CONTRIBUINTE.search(texto)
                    if m:
                        contribuinte_nome = m.group(1).strip()
                        contribuinte_cnpj = re.sub(r'\D', '', m.group(2))
                if municipio_nome is None:
                    m = self._RE_MUNICIPIO.search(texto)
                    if m:
                        municipio_nome = m.group(1).strip()

                linhas = texto.split("\n")
                for i, linha in enumerate(linhas):
                    m = self._RE_HEADER.match(linha)
                    if not m:
                        continue
                    cnpj_mask, _nome, dt_emissao, _tipo, _num_ini, _num_fim = m.groups()
                    cnpj_digits = re.sub(r'\D', '', cnpj_mask)
                    dt_norm = re.sub(r'\D', '', dt_emissao)
                    total_notas += 1

                    for j in range(i + 1, min(i + 4, len(linhas))):
                        if self._RE_HEADER.match(linhas[j]):
                            break  # já é a próxima nota; não achou a linha de serviço
                        md = self._RE_SERVICO_DADO.match(linhas[j])
                        if md:
                            valor_cents = self._parse_valor_br(md.group(4))
                            if valor_cents is not None:
                                livro_set[(cnpj_digits, dt_norm, valor_cents)] += 1
                            break

        return contribuinte_cnpj, contribuinte_nome, livro_set, total_notas, municipio_nome

    # ------------------------------------------------------------------
    # LEITURA DO XML DA NFS-e
    # ------------------------------------------------------------------
    def _strip_ns(self, s):
        s = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', s)
        s = re.sub(r'<(/?)(?:\w[\w.-]*:)', r'<\1', s)
        return s

    def _parse_nota_xml(self, xml_bytes):
        xml_str = xml_bytes.decode("utf-8", errors="ignore")
        xml_clean = self._strip_ns(xml_str)
        try:
            root = ET.fromstring(xml_clean)
        except ET.ParseError:
            return None

        def get_tag(tag, default=""):
            tl = tag.lower()
            for el in root.iter():
                if el.tag.lower() == tl:
                    return (el.text or "").strip()
            return default

        def get_path(path, default=""):
            el = root.find(".//" + path)
            return (el.text or "").strip() if el is not None else default

        def get_float(tags, default=0.0):
            for tag in tags:
                v = get_tag(tag)
                if v:
                    try:
                        return float(v.replace(",", "."))
                    except Exception:
                        pass
            return default

        numero_raw = get_tag("nNFSe") or get_tag("nDPS")
        if not numero_raw:
            return None
        numero = int(re.sub(r'\D', '', numero_raw) or "0")

        cnpj_prest = re.sub(r'\D', '', get_path("prest/CNPJ"))
        if not cnpj_prest:
            return None
        nome_prest = (get_path("prest/xNome") or get_path("prest/xFant")
                      or get_path("emit/xNome") or "-")

        cnpj_toma = re.sub(r'\D', '', get_path("toma/CNPJ") or get_path("toma/CPF"))
        cmun_toma = get_path("toma/end/endNac/cMun")

        d_compet = get_tag("dCompet")

        c_loc_prest = get_tag("cLocPrestacao") or get_path("prest/end/endNac/cMun")
        c_trib_nac = re.sub(r'\D', '', get_tag("cTribNac"))
        trib_issqn = get_path("valores/trib/tribMun/tribISSQN")

        v_serv = get_float(["vServ"])
        if v_serv == 0.0:
            v_serv = get_float(["vBC"])
        v_liq = get_float(["vLiq"])

        aliq_iss = get_float(["pAliqAplic", "pAliq"])

        opt_raw = get_tag("opSimpNac") or get_tag("optSimpNac")
        eh_optante = "S" if opt_raw in ("2", "3") else "N"

        m_cstat = re.search(r'<(?:\w+:)?cStat>\s*(\d+)\s*</(?:\w+:)?cStat>', xml_str)
        c_stat = m_cstat.group(1) if m_cstat else ""
        is_cancel = c_stat in self.CODIGOS_CANCELAMENTO

        return {
            "numero": numero,
            "cnpj_prest": cnpj_prest,
            "nome_prest": nome_prest,
            "cnpj_toma": cnpj_toma,
            "cmun_toma": cmun_toma,
            "d_compet": d_compet,
            "c_loc_prest": c_loc_prest,
            "c_trib_nac": c_trib_nac,
            "trib_issqn": trib_issqn,
            "v_serv": v_serv,
            "v_liq": v_liq,
            "aliq_iss": aliq_iss,
            "eh_optante": eh_optante,
            "is_cancel": is_cancel,
        }

    # ------------------------------------------------------------------
    # GERAÇÃO DO ARQUIVO-TEXTO (LEIAUTE OFICIAL)
    # ------------------------------------------------------------------
    def _f_alfa(self, valor, tamanho):
        s = (valor or "")[:tamanho]
        return s.ljust(tamanho)

    def _f_num(self, valor, tamanho):
        s = re.sub(r'\D', '', str(valor or "0")) or "0"
        return s[-tamanho:].zfill(tamanho)

    def _f_valor(self, valor, tamanho=15):
        centavos = int(round(float(valor or 0) * 100))
        return str(max(centavos, 0)).zfill(tamanho)

    def _f_data(self, data_iso, tamanho=8):
        try:
            dt = datetime.strptime((data_iso or "")[:10], "%Y-%m-%d")
            return dt.strftime("%d%m%Y")
        except Exception:
            return " " * tamanho

    def _competencia_pasta(self, data_iso):
        try:
            dt = datetime.strptime((data_iso or "")[:10], "%Y-%m-%d")
            return f"{self.MESES_PT[dt.month]} {dt.year}"
        except Exception:
            return "SEM COMPETENCIA"

    def _linha_prefeitura(self, cnpj_prefeitura):
        # Registro "0": obrigatório neste portal, deve ser a primeira linha do arquivo.
        return "0" + self._f_num(cnpj_prefeitura, 14) + "001"

    def _linha_declaracao(self, cnpj_declarante, nome_declarante, dt_inicial_iso, dt_final_iso):
        # Registro "1": identifica o DECLARANTE (empresa que está importando o arquivo),
        # não os prestadores das notas individuais (esses vão no registro "2").
        return (
            "1" + "T" + "1"
            + self._f_alfa(cnpj_declarante, 14)
            + self._f_alfa(nome_declarante, 50)
            + self._f_data(dt_inicial_iso)
            + self._f_data(dt_final_iso)
        )

    def _linha_documento(self, n):
        if n["is_cancel"]:
            situacao = "C"
        elif n["v_liq"] and n["v_serv"] > n["v_liq"]:
            situacao = "R"
        else:
            situacao = "N"
        return (
            "2"
            + self._f_alfa(n["cnpj_prest"], 14)
            + self._f_alfa(n["nome_prest"], 50)
            + (" " * 6)  # série: campo nulo — não temos como saber a série cadastrada/ativa no portal
            + self._f_num(n["numero"], 9)
            + self._f_num(n["numero"], 9)
            + self._f_data(n["d_compet"])
            + "N"
            + situacao
            + self._f_valor(n["v_serv"])
            + n["localizado"]
            + self._f_num(n["c_loc_prest"], 7)
            + n["eh_optante"]
            + (" " * 512)
            + n["natureza_operacao"]
        )

    def _linha_servico(self, n):
        cod = n["c_trib_nac"]
        lista_serv = f"{cod[0:2]}{cod[2:6]}" if len(cod) == 6 else self._f_alfa(cod, 7)
        aliq = n["aliq_iss"]
        aliq_2 = str(int(round(aliq * 100))).zfill(4)[-4:]
        return (
            "3"
            + self._f_alfa(lista_serv, 7)
            + self._f_valor(n["v_serv"])
            + self._f_num(n["c_loc_prest"], 7)
            + aliq_2
            + "   "
            + (" " * 6)  # aliquota 4 casas: em branco — só um dos dois campos de alíquota pode ser informado
        )

    def _gerar_arquivo_importacao(self, ausentes, cnpj_prefeitura, cnpj_declarante, nome_declarante, caminho_txt):
        datas = sorted(n["d_compet"] for n in ausentes if n.get("d_compet"))
        dt_inicial = datas[0] if datas else ""
        dt_final = datas[-1] if datas else ""

        linhas = [
            self._linha_prefeitura(cnpj_prefeitura),
            self._linha_declaracao(cnpj_declarante, nome_declarante, dt_inicial, dt_final),
        ]
        for n in ausentes:
            linhas.append(self._linha_documento(n))
            # Regra do manual: notas canceladas/anuladas não levam registro de Serviços (3)
            if not n["is_cancel"]:
                linhas.append(self._linha_servico(n))

        conteudo = "\r\n".join(linhas) + "\r\n"
        dados = conteudo.encode("cp1252", errors="replace")
        with open(caminho_txt, "wb") as f:
            f.write(dados)
        return len(dados) / 1024
