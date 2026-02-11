from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime
import uuid
import requests
import json
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Importações para PostgreSQL
try:
    import psycopg2
    import psycopg2.extras
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

# Carrega variáveis de ambiente
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev_secret_key_change_in_production')
CORS(app)

# Configurações
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
os.makedirs('/tmp', exist_ok=True)
DATABASE_URL = os.getenv('DATABASE_URL', '/tmp/leads.db')

class LeadManager:
    """Gerencia operações de banco de dados para leads - SQLite e PostgreSQL"""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.is_postgres = db_url.startswith('postgresql://') or db_url.startswith('postgres://')
        
        if self.is_postgres and not POSTGRES_AVAILABLE:
            raise ImportError("psycopg2 não está instalado. Execute: pip install psycopg2-binary")
        
        self.init_database()
    
    def get_connection(self):
        """Retorna conexão apropriada (SQLite ou PostgreSQL)"""
        if self.is_postgres:
            # Corrige URL do postgres para postgresql se necessário
            db_url = self.db_url.replace('postgres://', 'postgresql://', 1)
            return psycopg2.connect(db_url)
        else:
            return sqlite3.connect(self.db_url)
    
    def init_database(self):
        """Inicializa as tabelas do banco"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                # PostgreSQL syntax
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT UNIQUE NOT NULL,
                        nome TEXT,
                        convenio TEXT,
                        especialidade TEXT,
                        procedimento TEXT,
                        sintomas TEXT,
                        telefone TEXT,
                        email TEXT,
                        agendado BOOLEAN DEFAULT FALSE,
                        conversa_completa TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS mensagens (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Criar índices para performance
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_leads_session ON leads(session_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_mensagens_session ON mensagens(session_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_mensagens_timestamp ON mensagens(timestamp)')
                
            else:
                # SQLite syntax (desenvolvimento)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT UNIQUE NOT NULL,
                        nome TEXT,
                        convenio TEXT,
                        especialidade TEXT,
                        procedimento TEXT,
                        sintomas TEXT,
                        telefone TEXT,
                        email TEXT,
                        agendado BOOLEAN DEFAULT FALSE,
                        conversa_completa TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS mensagens (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            
            conn.commit()
            conn.close()
            print(f"✅ Banco {'PostgreSQL' if self.is_postgres else 'SQLite'} inicializado com sucesso")
            
        except Exception as e:
            print(f"❌ Erro ao inicializar banco: {e}")
            raise
    
    def create_lead(self, session_id: str) -> bool:
        """Cria um novo lead na base"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute(
                    'INSERT INTO leads (session_id) VALUES (%s) ON CONFLICT (session_id) DO NOTHING',
                    (session_id,)
                )
            else:
                cursor.execute('INSERT OR IGNORE INTO leads (session_id) VALUES (?)', (session_id,))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Erro ao criar lead: {e}")
            return False
    
    def update_lead(self, session_id: str, data: Dict) -> bool:
        """Atualiza dados do lead"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Campos permitidos
            allowed_fields = ['nome', 'convenio', 'especialidade', 'procedimento', 'sintomas',
                            'telefone', 'email', 'agendado', 'conversa_completa']
            
            # Monta query dinâmica baseada nos campos fornecidos
            fields = []
            values = []
            for key, value in data.items():
                if key in allowed_fields:
                    if self.is_postgres:
                        fields.append(f"{key} = %s")
                    else:
                        fields.append(f"{key} = ?")
                    values.append(value)
            
            if fields:
                if self.is_postgres:
                    query = f"UPDATE leads SET {', '.join(fields)} WHERE session_id = %s"
                else:
                    query = f"UPDATE leads SET {', '.join(fields)} WHERE session_id = ?"
                values.append(session_id)
                cursor.execute(query, values)
                conn.commit()
            
            conn.close()
            return True
        except Exception as e:
            print(f"Erro ao atualizar lead: {e}")
            return False
    
    def save_message(self, session_id: str, role: str, content: str) -> bool:
        """Salva uma mensagem no histórico"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute(
                    'INSERT INTO mensagens (session_id, role, content) VALUES (%s, %s, %s)',
                    (session_id, role, content)
                )
            else:
                cursor.execute(
                    'INSERT INTO mensagens (session_id, role, content) VALUES (?, ?, ?)',
                    (session_id, role, content)
                )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Erro ao salvar mensagem: {e}")
            return False
    
    def get_conversation_history(self, session_id: str) -> List[Dict]:
        """Recupera histórico da conversa"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute(
                    'SELECT role, content, timestamp FROM mensagens WHERE session_id = %s ORDER BY timestamp ASC',
                    (session_id,)
                )
            else:
                cursor.execute(
                    'SELECT role, content, timestamp FROM mensagens WHERE session_id = ? ORDER BY timestamp ASC',
                    (session_id,)
                )
            
            messages = []
            for row in cursor.fetchall():
                messages.append({
                    'role': row[0],
                    'content': row[1],
                    'timestamp': str(row[2])
                })
            conn.close()
            return messages
        except Exception as e:
            print(f"Erro ao recuperar histórico: {e}")
            return []
    
    def get_leads_stats(self) -> Dict:
        """Retorna estatísticas dos leads"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute('''
                    SELECT
                        COUNT(*) as total_leads,
                        COUNT(CASE WHEN agendado = true THEN 1 END) as leads_agendados,
                        COUNT(CASE WHEN nome IS NOT NULL THEN 1 END) as leads_com_nome,
                        COUNT(CASE WHEN email IS NOT NULL THEN 1 END) as leads_com_email
                    FROM leads
                ''')
            else:
                cursor.execute('''
                    SELECT
                        COUNT(*) as total_leads,
                        COUNT(CASE WHEN agendado = 1 THEN 1 END) as leads_agendados,
                        COUNT(CASE WHEN nome IS NOT NULL THEN 1 END) as leads_com_nome,
                        COUNT(CASE WHEN email IS NOT NULL THEN 1 END) as leads_com_email
                    FROM leads
                ''')
            
            row = cursor.fetchone()
            conn.close()
            
            return {
                'total_leads': row[0],
                'leads_agendados': row[1],
                'leads_com_nome': row[2],
                'leads_com_email': row[3],
                'taxa_agendamento': round((row[1] / row[0] * 100) if row[0] > 0 else 0, 1)
            }
        except Exception as e:
            print(f"Erro ao buscar estatísticas: {e}")
            return {'total_leads': 0, 'leads_agendados': 0, 'leads_com_nome': 0, 'leads_com_email': 0, 'taxa_agendamento': 0}

class ClinicaChatbot:
    """Chatbot de vendas para clínicas médicas"""
    
    def __init__(self, groq_api_key: str):
        self.api_key = groq_api_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        
        # Prompt base - Assistente de Vendas para Clínicas
        self.system_prompt = """
# Nexus AI - Assistente Virtual de Vendas para Clínicas

## REGRA NÚMERO 1 - FOCO TOTAL EM AGENDAMENTO:
Você é um assistente virtual de atendimento de clínica médica. Seu objetivo principal é AGENDAR CONSULTAS e PROCEDIMENTOS.
- NUNCA responda perguntas que não estejam relacionadas à clínica, saúde ou serviços oferecidos
- Se o paciente desviar o assunto, redirecione educadamente: "Entendo! Mas voltando ao que importa pra sua saúde..."
- Você NÃO é um assistente geral, NÃO dá diagnósticos médicos, NÃO prescreve medicamentos

## SEU PERFIL:
- Amigável e acolhedor
- Profissional mas não robótico
- Empático com preocupações de saúde
- Confiante ao apresentar a clínica e os profissionais
- CONVERSACIONAL: uma pergunta por vez, construindo rapport
- Sempre usa o nome do paciente quando souber
- Usa emojis com moderação (1-2 por mensagem)
- Mensagens curtas: máximo 5-6 linhas por resposta

## DADOS DA CLÍNICA (adaptar conforme configuração):
- Nome: [NOME DA CLÍNICA] (usar o nome configurado ou "nossa clínica")
- Especialidades disponíveis: Clínica Geral, Cardiologia, Dermatologia, Ortodontia, e outras conforme configuração
- Aceita convênios e atendimento particular
- Formas de pagamento: dinheiro, cartão (parcelamento disponível), PIX

## FLUXO DE ATENDIMENTO:

### ETAPA 1 - SAUDAÇÃO E IDENTIFICAÇÃO
Objetivo: Criar rapport e identificar o interesse.
- Cumprimente de forma acolhedora
- Pergunte o nome do paciente
- Identifique o interesse inicial

Variações de entrada do paciente:
- "Quero agendar consulta" → Siga para qualificação de especialidade
- "Quanto custa?" → Pergunte se tem convênio ou particular
- "Vocês atendem [convênio]?" → Responda sobre convênios
- "Preciso de informações" → Identifique a necessidade

### ETAPA 2 - QUALIFICAÇÃO INICIAL
Objetivo: Entender a necessidade e urgência.

Se pergunta sobre consulta/procedimento:
- Pergunte se é primeira vez com o especialista
- Pergunte se tem sintomas ou é check-up/prevenção

Se pergunta sobre preço:
- Pergunte se tem plano de saúde ou seria particular

Se pergunta sobre convênio:
- Pergunte qual o plano
- Se aceita: confirme e siga para agendamento
- Se não aceita: informe e ofereça valor particular acessível

### ETAPA 3 - APRESENTAÇÃO DA CLÍNICA
Objetivo: Construir credibilidade e valor.
- Tempo de atuação da clínica
- Corpo clínico qualificado (nome, CRM, experiência)
- Avaliações positivas (Google, etc.)
- Localização e diferenciais (estacionamento, acessibilidade)
- Pergunte se quer agendar

### ETAPA 4 - TRATAMENTO DE OBJEÇÕES

**"Está caro" / "Não tenho esse valor agora":**
- Explique o que está incluído no valor (consulta completa, retorno sem custo, etc.)
- Ofereça parcelamento no cartão
- Ofereça agendar para data futura para se programar
- Reforce que resolver no início economiza no médio prazo

**"Preciso pensar" / "Vou consultar família":**
- Pergunte o que está gerando dúvida (valor? médico? horário?)
- Garanta que tem todas as informações
- Ofereça pré-reserva de horário por tempo limitado
- Proponha enviar mensagem no dia seguinte

**"Não conheço o médico":**
- Apresente formação completa (universidade, residência, especialização)
- Destaque experiência e número de procedimentos
- Mencione avaliações e CRM
- Ofereça enviar link do currículo/avaliações

**"Qual a diferença para o concorrente?":**
- Destaque 2-3 diferenciais concretos (tempo de consulta, tecnologia, retorno incluso)
- Pergunte o que é mais importante para o paciente
- Conecte diferenciais às prioridades do paciente

**"Não tenho horário disponível":**
- Ofereça opções em diferentes períodos (manhã, tarde, fim do dia, sábado)
- Se realmente não tiver horário: ofereça lista de espera prioritária

**"Vocês fazem [procedimento]?":**
- Se sim: explique o processo, valor e ofereça agendamento
- Se não: indique clínica parceira e ofereça outro serviço

### ETAPA 5 - AGENDAMENTO
Objetivo: Fechar o agendamento.
- Ofereça 2-3 opções de horário (não mais)
- Aguarde escolha
- Confirme com resumo completo: paciente, procedimento, médico, data, horário, local, valor

### ETAPA 6 - CONFIRMAÇÃO E ORIENTAÇÕES
- Confirme o agendamento
- Informe o que trazer (documento, carteirinha, exames anteriores)
- Peça para chegar 15 min antes
- Informe política de remarcação (24h antecedência)
- Informe endereço completo
- Diga que enviará confirmação 24h antes

## ESPECIALIDADES - ABORDAGENS ESPECÍFICAS:

### CARDIOLOGIA:
- Pergunte sobre sintomas (dor no peito, falta de ar, palpitações)
- Pergunte sobre histórico familiar
- Destaque: consulta + ECG no mesmo dia, teste ergométrico, MAPA/Holter, ecocardiograma
- Se sintomas urgentes: priorize encaixe rápido

### ORTODONTIA:
- Abordagem leve e motivacional sobre sorriso
- Pergunte se já usou aparelho antes
- Apresente opções: fixo metálico, estético, alinhadores invisíveis
- Destaque avaliação gratuita
- Use comparação "menos que um café por dia" para valores parcelados

### DERMATOLOGIA ESTÉTICA:
- Pergunte sobre tratamento facial, corporal ou outro
- Pergunte se já fez procedimento antes e resultado esperado
- Explique: o que faz, tempo de sessão, número de sessões, recuperação
- Se medo do procedimento: reforce segurança (Anvisa), conforto, avaliação prévia completa

## FLUXOS DE EMERGÊNCIA:

### URGÊNCIA MÉDICA:
Se o paciente descrever sintomas graves (dor forte no peito, dificuldade respiratória severa, sangramento intenso, etc.):
- Oriente a ir ao pronto-socorro IMEDIATAMENTE
- Informe SAMU: 192
- NÃO tente avaliar à distância
- Reforce: "Sua saúde é prioridade! Busque atendimento presencial agora."

### FORA DO ESCOPO:
Se a solicitação não pode ser resolvida online:
- Oriente consulta presencial
- Ofereça agendar avaliação

## COLETA DE CONTATO:
- Colete nome, telefone/WhatsApp e email quando possível
- Para agendamento, peça: nome completo, telefone e email
- Se resistir: "É só para enviar a confirmação do agendamento"

## REGRAS DE OURO:

### FAÇA:
- UMA pergunta por vez
- Use SEMPRE o nome após descobri-lo
- Referencie respostas anteriores
- Ofereça 2-3 opções de horário
- Seja empático com preocupações de saúde
- Confirme agendamento com TODOS os detalhes
- Use tom brasileiro informal mas profissional
- Respostas curtas (máximo 5-6 linhas)

### NÃO FAÇA:
- Múltiplas perguntas na mesma resposta
- Usar jargões médicos excessivos
- Ser insistente demais (máximo 2 tentativas de objeção)
- Dar diagnósticos ou prescrições médicas
- Ignorar sinais de urgência médica
- Ser robótico ou genérico
- Responder perguntas totalmente off-topic

## GATILHOS DE ESCALAÇÃO PARA HUMANO:
- Paciente muito insatisfeito/bravo
- Situação de emergência médica
- Solicitação explícita para falar com humano
- Mais de 3 objeções consecutivas sem agendar
- Reclamação sobre atendimento anterior
- Pedido de cancelamento de consulta agendada
→ Nestes casos, diga: "Vou te transferir para nossa equipe de atendimento para te ajudar melhor. Um momento!"

## RETORNO E REATIVAÇÃO:
Se o paciente mencionou que já conversou antes ou se for retorno:
- "Que bom te ver de novo! Como posso te ajudar hoje?"
- Se for retorno de consulta: lembre do acompanhamento

## OBJETIVO FINAL:
AGENDAR A CONSULTA/PROCEDIMENTO e garantir que o paciente saia com todas as informações necessárias.
NUNCA deixar o paciente ir embora sem ao menos coletar o contato para follow-up.
"""
    
    def get_response(self, message: str, conversation_history: List[Dict]) -> str:
        """Gera resposta do chatbot usando Groq API"""
        
        # Prepara mensagens para a API
        messages = [{"role": "system", "content": self.system_prompt}]
        
        # Adiciona histórico da conversa (últimas 8 mensagens para não exceder limite)
        recent_history = conversation_history[-8:] if len(conversation_history) > 8 else conversation_history
        for msg in recent_history:
            messages.append({
                "role": msg['role'],
                "content": msg['content']
            })
        
        # Adiciona mensagem atual
        messages.append({"role": "user", "content": message})
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 400,
                "top_p": 0.9
            }
            
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            return result['choices'][0]['message']['content'].strip()
            
        except requests.exceptions.Timeout:
            return "Ops, demorei um pouco para responder. Pode repetir sua pergunta?"
        except requests.exceptions.HTTPError as e:
            print(f"Erro HTTP na API Groq: {e}")
            return "Tive um probleminha técnico. Pode tentar novamente?"
        except Exception as e:
            print(f"Erro na API Groq: {e}")
            return "Ops, tive um problema técnico. Pode repetir sua pergunta?"

# Instâncias globais
try:
    lead_manager = LeadManager(DATABASE_URL)
    chatbot = ClinicaChatbot(GROQ_API_KEY) if GROQ_API_KEY else None
    print("✅ Sistema inicializado com sucesso")
except Exception as e:
    print(f"❌ Erro na inicialização: {e}")
    lead_manager = None
    chatbot = None

@app.route('/')
def index():
    """Página principal do chat"""
    # Cria nova sessão se não existir
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        # Cria lead na base
        if lead_manager:
            lead_manager.create_lead(session['session_id'])
    
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    """Endpoint para processar mensagens do chat"""
    if not chatbot:
        return jsonify({'error': 'Chatbot não configurado. Verifique GROQ_API_KEY.'}), 500
    
    if not lead_manager:
        return jsonify({'error': 'Sistema de banco não configurado.'}), 500
    
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return jsonify({'error': 'Mensagem vazia'}), 400
        
        session_id = session.get('session_id')
        if not session_id:
            return jsonify({'error': 'Sessão inválida'}), 400
        
        # Salva mensagem do usuário
        lead_manager.save_message(session_id, 'user', user_message)
        
        # Recupera histórico
        history = lead_manager.get_conversation_history(session_id)
        
        # Gera resposta do bot
        bot_response = chatbot.get_response(user_message, history)
        
        # Salva resposta do bot
        lead_manager.save_message(session_id, 'assistant', bot_response)
        
        return jsonify({
            'response': bot_response,
            'session_id': session_id
        })
        
    except Exception as e:
        print(f"Erro no chat: {e}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/health')
def health():
    """Health check do sistema"""
    health_status = {
        'status': 'ok',
        'groq_configured': bool(GROQ_API_KEY),
        'database': 'connected' if lead_manager else 'error',
        'database_type': 'PostgreSQL' if DATABASE_URL.startswith('postgresql') else 'SQLite',
        'environment': os.getenv('FLASK_ENV', 'development')
    }
    
    if lead_manager:
        try:
            stats = lead_manager.get_leads_stats()
            health_status.update(stats)
        except:
            health_status['database'] = 'error'
    
    return jsonify(health_status)

@app.route('/admin/leads')
def admin_leads():
    """Página administrativa para ver leads capturados"""
    if not lead_manager:
        return "Sistema de banco não configurado", 500
    
    try:
        conn = lead_manager.get_connection()
        cursor = conn.cursor()
        
        if lead_manager.is_postgres:
            cursor.execute('''
                SELECT l.*, COUNT(m.id) as total_mensagens
                FROM leads l
                LEFT JOIN mensagens m ON l.session_id = m.session_id
                GROUP BY l.id, l.session_id, l.nome, l.convenio, l.especialidade, l.procedimento,
                         l.sintomas, l.telefone, l.email, l.agendado,
                         l.conversa_completa, l.created_at
                ORDER BY l.created_at DESC
            ''')
        else:
            cursor.execute('''
                SELECT l.*, COUNT(m.id) as total_mensagens 
                FROM leads l 
                LEFT JOIN mensagens m ON l.session_id = m.session_id 
                GROUP BY l.id 
                ORDER BY l.created_at DESC
            ''')
        
        leads = cursor.fetchall()
        conn.close()
        
        # Buscar estatísticas
        stats = lead_manager.get_leads_stats()
        
        leads_data = []
        for lead in leads:
            leads_data.append({
                'id': lead[0],
                'session_id': lead[1],
                'nome': lead[2] or 'N/A',
                'convenio': lead[3] or 'N/A',
                'especialidade': lead[4] or 'N/A',
                'procedimento': lead[5] or 'N/A',
                'sintomas': lead[6] or 'N/A',
                'telefone': lead[7] or 'N/A',
                'email': lead[8] or 'N/A',
                'agendado': 'Sim' if lead[9] else 'Não',
                'created_at': str(lead[11]),
                'total_mensagens': lead[12] if len(lead) > 12 else 0
            })
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Admin - Nexus AI Clínica</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                    margin: 0; padding: 20px; background: #f8fafc; 
                }}
                .header {{ 
                    background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%); 
                    color: white; padding: 2rem; border-radius: 12px; margin-bottom: 2rem; 
                }}
                .stats {{ 
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
                    gap: 1rem; margin-bottom: 2rem; 
                }}
                .stat-card {{ 
                    background: white; padding: 1.5rem; border-radius: 12px; 
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
                }}
                .stat-number {{ font-size: 2rem; font-weight: bold; color: #2563eb; }}
                .stat-label {{ color: #64748b; font-size: 0.875rem; }}
                table {{ 
                    background: white; border-collapse: collapse; width: 100%; 
                    border-radius: 12px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
                }}
                th, td {{ border: 1px solid #e2e8f0; padding: 12px; text-align: left; }}
                th {{ background-color: #f8fafc; font-weight: 600; }}
                .qualified {{ color: #059669; font-weight: bold; }}
                .not-qualified {{ color: #d97706; }}
                .back-link {{ 
                    display: inline-block; margin-top: 2rem; padding: 0.75rem 1.5rem; 
                    background: #2563eb; color: white; text-decoration: none; 
                    border-radius: 8px; transition: background 0.2s; 
                }}
                .back-link:hover {{ background: #1d4ed8; }}
                .empty-state {{ 
                    text-align: center; padding: 4rem; color: #64748b; 
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Nexus AI - Dashboard Administrativo</h1>
                <p>Gestão de pacientes e agendamentos</p>
                <p><strong>Banco:</strong> {'PostgreSQL' if lead_manager.is_postgres else 'SQLite'} |
                   <strong>Ambiente:</strong> {os.getenv('FLASK_ENV', 'development')}</p>
            </div>

            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number">{stats['total_leads']}</div>
                    <div class="stat-label">Total de Pacientes</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['leads_agendados']}</div>
                    <div class="stat-label">Agendamentos</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['taxa_agendamento']}%</div>
                    <div class="stat-label">Taxa de Agendamento</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['leads_com_email']}</div>
                    <div class="stat-label">Pacientes com Email</div>
                </div>
            </div>
        """
        
        if leads_data:
            html += """
            <table>
                <tr>
                    <th>Data</th>
                    <th>Nome</th>
                    <th>Convenio</th>
                    <th>Especialidade</th>
                    <th>Procedimento</th>
                    <th>Sintomas</th>
                    <th>Telefone</th>
                    <th>Email</th>
                    <th>Agendado</th>
                    <th>Mensagens</th>
                </tr>
            """

            for lead in leads_data:
                agendado_class = 'qualified' if lead['agendado'] == 'Sim' else 'not-qualified'
                sintomas_truncado = (lead['sintomas'][:30] + '...'
                                   if len(lead['sintomas']) > 30 else lead['sintomas'])
                html += f"""
                    <tr>
                        <td>{lead['created_at'][:16]}</td>
                        <td>{lead['nome']}</td>
                        <td>{lead['convenio']}</td>
                        <td>{lead['especialidade']}</td>
                        <td>{lead['procedimento']}</td>
                        <td title="{lead['sintomas']}">{sintomas_truncado}</td>
                        <td>{lead['telefone']}</td>
                        <td>{lead['email']}</td>
                        <td class="{agendado_class}">{lead['agendado']}</td>
                        <td>{lead['total_mensagens']}</td>
                    </tr>
                """
            
            html += "</table>"
        else:
            html += """
            <div class="empty-state">
                <h3>Nenhum paciente registrado ainda</h3>
                <p>Quando alguem conversar com o chatbot, os dados aparecerao aqui.</p>
            </div>
            """
        
        html += """
            <a href="/" class="back-link">← Voltar ao chat</a>
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        return f"Erro ao carregar leads: {e}", 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 7860))
    debug = os.getenv('FLASK_ENV') != 'production'
    
    print("NEXUS AI - Assistente Virtual para Clinicas")
    print("=" * 50)
    print(f"Ambiente: {os.getenv('FLASK_ENV', 'development')}")
    print(f"Porta: {port}")
    print(f"Banco: {'PostgreSQL' if DATABASE_URL.startswith('postgresql') else 'SQLite'}")
    print(f"Groq API: {'Configurada' if GROQ_API_KEY else 'Nao configurada'}")
    print(f"Admin: http://localhost:{port}/admin/leads")
    print(f"Chat: http://localhost:{port}")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=port, debug=debug)