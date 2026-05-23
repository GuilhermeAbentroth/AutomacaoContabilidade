import customtkinter as ctk
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox
import threading
import os
import time
import re
import json
import pandas as pd
import requests
import warnings
from lxml import etree
from signxml import XMLSigner
from certificado_utils import CertificadoA1

# Silencia avisos técnicos do certificado
warnings.filterwarnings("ignore", category=UserWarning, message=".*PKCS#12 bundle could not be parsed.*")


class EmissorBethaCertificado:
    CONFIG_FILE = "config_emissor.json"

    def __init__(self, parent):
        self.parent = parent
        self.container = parent.container
        self.config = self.carregar_configuracoes()

    def carregar_configuracoes(self):
        """Carrega os dados salvos da última sessão."""
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def salvar_configuracoes(self):
        """Salva os dados atuais para a próxima sessão."""
        dados = {
            "cnpj_prestador": self.ent_cnpj_prest.get(),
            "im_prestador": self.ent_im_prest.get(),
            "caminho_excel": self.ent_excel.get(),
            "caminho_pfx": self.ent_pfx.get()
        }
        with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(dados, f, indent=4)

    def tela_emissor_certificado(self):
        self.parent.limpar_tela()

        f_top = ctk.CTkFrame(self.container, fg_color="transparent")
        f_top.pack(pady=10)
        self.parent.carregar_logo(f_top)

        ctk.CTkLabel(self.container, text="Emissor NFSE - Padrão Nota Nacional (Betha)",
                     font=("Arial", 22, "bold"), text_color="#27ae60").pack(pady=10)

        # --- DADOS DO PRESTADOR ---
        f_prest = ctk.CTkFrame(self.container)
        f_prest.pack(fill="x", padx=40, pady=5)
        ctk.CTkLabel(f_prest, text="DADOS DA EMPRESA EMISSORA (PRESTADOR)", font=("Arial", 12, "bold")).pack(pady=5)

        f_line_p = ctk.CTkFrame(f_prest, fg_color="transparent")
        f_line_p.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(f_line_p, text="CNPJ Prestador:", width=100, anchor="w").pack(side="left")
        self.ent_cnpj_prest = ctk.CTkEntry(f_line_p, width=200)
        self.ent_cnpj_prest.insert(0, self.config.get("cnpj_prestador", ""))
        self.ent_cnpj_prest.pack(side="left", padx=10)

        ctk.CTkLabel(f_line_p, text="Inscrição Municipal:", width=120, anchor="w").pack(side="left")
        self.ent_im_prest = ctk.CTkEntry(f_line_p, width=150)
        self.ent_im_prest.insert(0, self.config.get("im_prestador", ""))
        self.ent_im_prest.pack(side="left", padx=10)

        # --- ARQUIVOS ---
        f_card = ctk.CTkFrame(self.container)
        f_card.pack(fill="x", padx=40, pady=10)
        self.ent_excel = self._criar_linha_arquivo(f_card, "Planilha Base:", self.config.get("caminho_excel", ""))
        self.ent_pfx = self._criar_linha_arquivo(f_card, "Certificado (.pfx):", self.config.get("caminho_pfx", ""))

        f_senha = ctk.CTkFrame(f_card, fg_color="transparent")
        f_senha.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(f_senha, text="Senha Certificado:", font=("Arial", 12, "bold"), width=120, anchor="w").pack(
            side="left")
        self.ent_senha_cert = ctk.CTkEntry(f_senha, show="*", width=200);
        self.ent_senha_cert.pack(side="left", padx=10)

        f_amb = ctk.CTkFrame(f_card, fg_color="transparent")
        f_amb.pack(fill="x", padx=20, pady=15)
        self.var_ambiente = ctk.StringVar(value="Produção (Real)")
        self.seg_amb = ctk.CTkSegmentedButton(f_amb, values=["Homologação (Testes)", "Produção (Real)"],
                                              variable=self.var_ambiente, width=350)
        self.seg_amb.pack(side="left", padx=10)

        f_log = ctk.CTkFrame(self.container)
        f_log.pack(fill="both", expand=True, padx=40, pady=10)
        self.parent.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=8, state='disabled', bg="#1e1e1e",
                                                        fg="white")
        self.parent.txt_log.pack(padx=10, pady=5, fill="both", expand=True)

        f_btns = ctk.CTkFrame(self.container, fg_color="transparent")
        f_btns.pack(pady=20)
        ctk.CTkButton(f_btns, text="🚀 INICIAR EMISSÃO NACIONAL", command=self.start_thread,
                      fg_color="#27ae60", hover_color="#1e8449", font=("Arial", 14, "bold"), height=50, width=300).pack(
            side="left", padx=10)
        ctk.CTkButton(f_btns, text="Voltar", command=self.parent.mostrar_menu_inicial, width=150, height=50,
                      fg_color="gray").pack(side="left")

    def _criar_linha_arquivo(self, parent, label, valor_inicial):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(f, text=label, font=("Arial", 12, "bold"), width=120, anchor="w").pack(side="left")
        entry = ctk.CTkEntry(f, width=400);
        entry.insert(0, valor_inicial);
        entry.pack(side="left", padx=10)
        ctk.CTkButton(f, text="...", width=40, command=lambda: self._selecionar(entry)).pack(side="left")
        return entry

    def _selecionar(self, entry):
        p = filedialog.askopenfilename()
        if p: entry.delete(0, tk.END); entry.insert(0, p)

    def start_thread(self):
        self.salvar_configuracoes()
        threading.Thread(target=self.processar_emissao, daemon=True).start()

    def processar_emissao(self):
        url_ws = "https://nota-eletronica.betha.cloud/dps/ws"
        tp_amb = "1" if "Produção" in self.var_ambiente.get() else "2"
        cnpj_p = "".join(filter(str.isdigit, self.ent_cnpj_prest.get()))
        im_p = self.ent_im_prest.get().strip()

        cert_manager = CertificadoA1(self.ent_pfx.get(), self.ent_senha_cert.get())
        if not cert_manager.carregar_chaves(self.parent.log_msg): return

        try:
            df = pd.read_excel(self.ent_excel.get())
            for i, row in df.iterrows():
                # --- VOLTANDO PARA A LÓGICA DE TEMPO ORIGINAL (Mas recuando 5 min) ---
                tempo_seguro = time.time() - 300
                dh_emi = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(tempo_seguro))
                dt_comp = time.strftime('%Y-%m-%d', time.localtime(tempo_seguro))

                num_v = str(int(time.time() * 1000) % 1000000000000000).zfill(15)
                id_45 = f"DPS42089062{cnpj_p.zfill(14)}{'900'.zfill(5)}{num_v}"

                dados = {
                    "id_45": id_45, "dhEmi": dh_emi, "dCompet": dt_comp,
                    "valor": f"{float(str(row.get('Serviço - Valor Serviço', 0)).replace(',', '.')):.2f}",
                    "cnpj_tomador": "".join(filter(str.isdigit, str(row.get('Tomador - CPF/CNPJ', '')))),
                    "cep_tomador": "".join(filter(str.isdigit, str(row.get('Tomador - CEP', '')))),
                    "logradouro": str(row.get('Tomador - Endereco', '')).upper()[:80],
                    "numero": str(row.get('Tomador - Número', 'SN')).upper()[:10],
                    "bairro": str(row.get('Tomador - Bairro', '')).upper()[:60],
                    "razao_social": str(row.get('Tomador - Nome/Razao Social', '')).upper()[:150],
                    "servico": str(row.get('Serviço - Discriminação', '')).upper(),
                    "item_lista": str(row.get('Serviço - Código Serviço', '1719')).replace('.', '').ljust(6, '0'),
                    "cnpj_prest": cnpj_p, "im_prest": im_p, "nDPS": num_v.lstrip('0') or "1"
                }

                self.parent.log_msg(f"Enviando DPS {i + 1}/{len(df)}...")
                xml_corpo = self._gerar_xml_dps_corpo(dados, tp_amb)
                xml_assinado = self._assinar_xml(xml_corpo, cert_manager)

                # --- LIMPEZA MANUAL IDÊNTICA AO CÓDIGO QUE FUNCIONAVA ---
                xml_limpo = xml_assinado.decode('utf-8').replace('<?xml version="1.0" encoding="UTF-8"?>', '').replace(
                    '<?xml version="1.0" ?>', '').strip()

                envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns="http://www.betha.com.br/e-nota-dps">
                    <soapenv:Body><RecepcionarDpsEnvio>{xml_limpo}</RecepcionarDpsEnvio></soapenv:Body>
                </soapenv:Envelope>"""

                resp = requests.post(url_ws, data=envelope.encode('utf-8'),
                                     headers={'Content-Type': 'text/xml;charset=UTF-8'}, timeout=60)

                # --- LOG DE SUCESSO MELHORADO (Ignora namespaces como ns2:protocolo) ---
                if resp.status_code == 200:
                    prot_match = re.search(r'protocolo>(.*?)</', resp.text, re.IGNORECASE)
                    if prot_match:
                        self.parent.log_msg(f"SUCESSO! Prot: {prot_match.group(1)}", "sucesso")
                    else:
                        msg_match = re.search(r'mensagem>(.*?)</', resp.text, re.IGNORECASE)
                        self.parent.log_msg(f"REJEITADA: {msg_match.group(1) if msg_match else 'Erro Betha'}", "erro")
                        print(f"DEBUG RETORNO: {resp.text}")
                else:
                    self.parent.log_msg(f"Erro HTTP {resp.status_code}", "erro")

                time.sleep(1.2)

        except Exception as e:
            self.parent.log_msg(f"Erro Crítico: {e}", "erro")

    def _assinar_xml(self, xml_string, cert_manager):
        root = etree.fromstring(xml_string.encode('utf-8'))
        signed_root = XMLSigner().sign(root, key=cert_manager.obter_chave_privada_pem(),
                                       cert=cert_manager.obter_certificado_pem())
        return etree.tostring(signed_root, encoding='utf-8', xml_declaration=False)

    def _gerar_xml_dps_corpo(self, d, tp_amb):
        return f"""<DPS xmlns="http://www.betha.com.br/e-nota-dps" versao="1.01">
            <infDPS id="{d['id_45']}">
                <tpAmb>{tp_amb}</tpAmb>
                <dhEmi>{d['dhEmi']}</dhEmi>
                <verAplic>Abentroth_v6.9</verAplic>
                <serie>900</serie>
                <nDPS>{d['nDPS']}</nDPS>
                <dCompet>{d['dCompet']}</dCompet>
                <tpEmit>1</tpEmit>
                <cLocEmi>4208906</cLocEmi>
                <prest>
                    <CNPJ>{d['cnpj_prest']}</CNPJ>
                    <IM>{d['im_prest']}</IM>
                    <regTrib><opSimpNac>3</opSimpNac><regApTribSN>2</regApTribSN><regEspTrib>0</regEspTrib></regTrib>
                </prest>
                <toma>
                    <CNPJ>{d['cnpj_tomador']}</CNPJ>
                    <xNome>{d['razao_social']}</xNome>
                    <end>
                        <endNac><cMun>4208906</cMun><CEP>{d['cep_tomador']}</CEP></endNac>
                        <xLgr>{d['logradouro']}</xLgr><nro>{d['numero']}</nro><xBairro>{d['bairro']}</xBairro>
                    </end>
                </toma>
                <serv>
                    <locPrest><cLocPrestacao>4208906</cLocPrestacao></locPrest>
                    <cServ>
                        <cTribNac>{d['item_lista']}</cTribNac>
                        <xDescServ>{d['servico']}</xDescServ>
                        <cNBS>101011200</cNBS>
                    </cServ>
                </serv>
                <valores>
                    <vServPrest><vServ>{d['valor']}</vServ></vServPrest>
                    <trib>
                        <tribMun><tribISSQN>1</tribISSQN><pAliq>5.00</pAliq><tpRetISSQN>1</tpRetISSQN></tribMun>
                        <totTrib><pTotTrib><pTotTribFed>0.00</pTotTribFed><pTotTribEst>0.00</pTotTribEst><pTotTribMun>0.00</pTotTribMun></pTotTrib></totTrib>
                    </trib>
                </valores>
            </infDPS>
        </DPS>"""