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
DATABASE_URL = os.getenv('DATABASE_URL', 'leads.db')

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
                        empresa TEXT,
                        segmento TEXT,
                        problema TEXT,
                        investimento_atual TEXT,
                        telefone TEXT,
                        email TEXT,
                        qualificado BOOLEAN DEFAULT FALSE,
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
                        empresa TEXT,
                        segmento TEXT,
                        problema TEXT,
                        investimento_atual TEXT,
                        telefone TEXT,
                        email TEXT,
                        qualificado BOOLEAN DEFAULT FALSE,
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
            allowed_fields = ['nome', 'empresa', 'segmento', 'problema', 'investimento_atual', 
                            'telefone', 'email', 'qualificado', 'conversa_completa']
            
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
                        COUNT(CASE WHEN qualificado = true THEN 1 END) as leads_qualificados,
                        COUNT(CASE WHEN nome IS NOT NULL THEN 1 END) as leads_com_nome,
                        COUNT(CASE WHEN email IS NOT NULL THEN 1 END) as leads_com_email
                    FROM leads
                ''')
            else:
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_leads,
                        COUNT(CASE WHEN qualificado = 1 THEN 1 END) as leads_qualificados,
                        COUNT(CASE WHEN nome IS NOT NULL THEN 1 END) as leads_com_nome,
                        COUNT(CASE WHEN email IS NOT NULL THEN 1 END) as leads_com_email
                    FROM leads
                ''')
            
            row = cursor.fetchone()
            conn.close()
            
            return {
                'total_leads': row[0],
                'leads_qualificados': row[1],
                'leads_com_nome': row[2],
                'leads_com_email': row[3],
                'taxa_qualificacao': round((row[1] / row[0] * 100) if row[0] > 0 else 0, 1)
            }
        except Exception as e:
            print(f"Erro ao buscar estatísticas: {e}")
            return {'total_leads': 0, 'leads_qualificados': 0, 'leads_com_nome': 0, 'leads_com_email': 0, 'taxa_qualificacao': 0}

class SDRChatbot:
    """Chatbot SDR para qualificação de leads"""
    
    def __init__(self, groq_api_key: str):
        self.api_key = groq_api_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        
        # Prompt base do SDR
        self.system_prompt = """
Você é um SDR (Sales Development Representative) especializado em qualificação de leads para Gustavo, especialista em aceleração de negócios através de ecossistemas digitais.

SEU PERFIL:
- Vendedor nato: direto, sem enrolação
- Data-driven: usa estatísticas como arma de persuasão
- Consultivo: eleva o nível de consciência do prospect
- Focado em ROI: sempre conecta problemas a perdas financeiras
- Personalizado: sempre usa o nome da pessoa e adapta a abordagem

POSICIONAMENTO DO GUSTAVO:
"Especialista em Aceleração de Negócios que une Web Design Estratégico + Análise de Performance + Automação + BI para gerar resultados reais e mensuráveis."

DIFERENCIAIS:
- Visão 360º: não entrega só site, mas ecossistema completo
- Métricas que importam: ROI, custo por cliente, LTV
- Diagnóstico profundo antes de qualquer proposta
- Dashboards estratégicos personalizados
- Automações humanizadas com integrações inteligentes

FLUXO DE QUALIFICAÇÃO PERSONALIZADO:

ETAPA 1 - PRIMEIRA INTERAÇÃO (Descoberta Inicial):
Sempre pergunte primeiro:
1. "Qual seu nome?"
2. "Você já conhece nosso trabalho ou é a primeira vez que ouve falar da gente?"
3. "O que te trouxe até aqui? Está buscando algo específico?"

ETAPA 2 - PERSONALIZAÇÃO (Use o nome + adapte):
Com base na resposta anterior:

Se JÁ CONHECE: "[Nome], que bom te encontrar aqui! Já que você conhece nosso trabalho, me conta: qual parte mais chamou sua atenção?"

Se NÃO CONHECE: "[Nome], perfeito! Deixa eu te explicar rapidamente: ajudo empresas a transformar visitantes em clientes usando dados reais. Qual é o seu negócio?"

Se BUSCA ALGO ESPECÍFICO: "[Nome], entendi que você está procurando [serviço específico]. Antes de tudo, me conta: qual o maior gargalo que está enfrentando com isso?"

ETAPA 3 - DESCOBERTA PROFUNDA:
Perguntas contextualizadas:
- "[Nome], me conta um pouco mais sobre como funciona seu processo de vendas hoje"
- "Qual métrica você mais acompanha no seu negócio?"
- "Quando foi a última vez que você conseguiu rastrear exatamente de onde veio uma venda?"

ETAPA 4 - ELEVAÇÃO DE CONSCIÊNCIA (Dados contextualizados):
Use dados quando fizer sentido na conversa:

E-commerce:
- "68% dos carrinhos são abandonados por UX ruim"
- "Cada segundo de demora no carregamento = 7% menos conversão"

Serviços:
- "Apenas 2% dos visitantes convertem na primeira visita"
- "87% das empresas não sabem de onde vêm seus clientes"
- "Empresas do seu segmento que conseguem rastrear a origem dos clientes vendem em média 67% mais"

B2B:
- "Empresas com funil estruturado vendem 67% mais"
- "90% das empresas não sabem quanto gastam para conquistar cada cliente"

ETAPA 5 - QUALIFICAÇÃO RÁPIDA:
Máximo 2 perguntas por vez, sempre usando o nome:
- "[Nome], quanto você investe por mês em marketing digital?"
- "Quem toma as decisões sobre isso na sua empresa?"

ETAPA 6 - FECHAMENTO CONSULTIVO:
"[Nome], pelo que você me contou, acho que uma análise rápida do seu cenário atual faria sentido. Quando você teria uns 30 minutos para conversarmos?"

PERSONALIZAÇÃO BASEADA NO HISTÓRICO:
- Sempre referencie o que a pessoa disse anteriormente
- "Como você mencionou que [problema específico], isso me lembra de um caso similar..."
- Use informações da conversa para contextualizar dados e sugestões

DADOS DE AUTORIDADE:
E-commerce:
- "68% dos carrinhos são abandonados por UX ruim"
- "Cada segundo de demora no carregamento = 7% menos conversão"

Serviços:
- "Apenas 2% dos visitantes convertem na primeira visita"
- "87% das empresas não sabem de onde vêm seus clientes"

B2B:
- "Empresas com funil estruturado vendem 67% mais"
- "90% das empresas não sabem quanto gastam para conquistar cada cliente"

CRITÉRIOS PARA LEAD QUALIFICADO:
✅ Tem negócio estabelecido
✅ Investe ou pretende investir em digital (>R$ 500/mês)
✅ Tem dor clara relacionada aos serviços
✅ Demonstra poder de decisão ou influência
✅ Mostra interesse em resultados mensuráveis
✅ Tem urgência ou timeline definido

IMPORTANTE:
- SEMPRE use o nome da pessoa após descobri-lo
- Adapte a abordagem conforme conhecimento prévio
- Seja DIRETO e OBJETIVO mas consultivo
- Use dados contextualizados na conversa
- Qualifique através de descoberta natural
- Conecte sempre problema = perda financeira
- Máximo 2 perguntas por resposta
- Foque no agendamento da análise gratuita
- Respostas de no máximo 3-4 linhas
- Tom brasileiro, informal mas profissional
- Personalize sempre baseado nas respostas anteriores


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
                "max_tokens": 250,
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
    chatbot = SDRChatbot(GROQ_API_KEY) if GROQ_API_KEY else None
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
                GROUP BY l.id, l.session_id, l.nome, l.empresa, l.segmento, l.problema, 
                         l.investimento_atual, l.telefone, l.email, l.qualificado, 
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
                'empresa': lead[3] or 'N/A',
                'segmento': lead[4] or 'N/A',
                'problema': lead[5] or 'N/A',
                'investimento_atual': lead[6] or 'N/A',
                'telefone': lead[7] or 'N/A',
                'email': lead[8] or 'N/A',
                'qualificado': 'Sim' if lead[9] else 'Não',
                'created_at': str(lead[11]),
                'total_mensagens': lead[12] if len(lead) > 12 else 0
            })
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>📊 Admin - SDR Chatbot Gustavo</title>
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
                <h1>📊 SDR Chatbot - Dashboard Administrativo</h1>
                <p>Gestão de leads e performance do Gustavo</p>
                <p><strong>Banco:</strong> {'PostgreSQL' if lead_manager.is_postgres else 'SQLite'} • 
                   <strong>Ambiente:</strong> {os.getenv('FLASK_ENV', 'development')}</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number">{stats['total_leads']}</div>
                    <div class="stat-label">Total de Leads</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['leads_qualificados']}</div>
                    <div class="stat-label">Leads Qualificados</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['taxa_qualificacao']}%</div>
                    <div class="stat-label">Taxa de Qualificação</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['leads_com_email']}</div>
                    <div class="stat-label">Leads com Email</div>
                </div>
            </div>
        """
        
        if leads_data:
            html += """
            <table>
                <tr>
                    <th>Data</th>
                    <th>Nome</th>
                    <th>Empresa</th>
                    <th>Segmento</th>
                    <th>Problema</th>
                    <th>Investimento</th>
                    <th>Telefone</th>
                    <th>Email</th>
                    <th>Qualificado</th>
                    <th>Mensagens</th>
                </tr>
            """
            
            for lead in leads_data:
                qualified_class = 'qualified' if lead['qualificado'] == 'Sim' else 'not-qualified'
                problema_truncado = (lead['problema'][:30] + '...' 
                                   if len(lead['problema']) > 30 else lead['problema'])
                html += f"""
                    <tr>
                        <td>{lead['created_at'][:16]}</td>
                        <td>{lead['nome']}</td>
                        <td>{lead['empresa']}</td>
                        <td>{lead['segmento']}</td>
                        <td title="{lead['problema']}">{problema_truncado}</td>
                        <td>{lead['investimento_atual']}</td>
                        <td>{lead['telefone']}</td>
                        <td>{lead['email']}</td>
                        <td class="{qualified_class}">{lead['qualificado']}</td>
                        <td>{lead['total_mensagens']}</td>
                    </tr>
                """
            
            html += "</table>"
        else:
            html += """
            <div class="empty-state">
                <h3>🤔 Nenhum lead capturado ainda</h3>
                <p>Quando alguém conversar com o chatbot, os dados aparecerão aqui.</p>
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
    port = int(os.getenv('PORT', 8000))
    debug = os.getenv('FLASK_ENV') != 'production'
    
    print("🚀 SDR CHATBOT DO GUSTAVO")
    print("=" * 50)
    print(f"🌍 Ambiente: {os.getenv('FLASK_ENV', 'development')}")
    print(f"🔧 Porta: {port}")
    print(f"🗃️ Banco: {'PostgreSQL' if DATABASE_URL.startswith('postgresql') else 'SQLite'}")
    print(f"🤖 Groq API: {'✅ Configurada' if GROQ_API_KEY else '❌ Não configurada'}")
    print(f"📊 Admin: http://localhost:{port}/admin/leads")
    print(f"💬 Chat: http://localhost:{port}")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=port, debug=debug)