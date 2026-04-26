# ------------------------------------------------------------
# constraintlex.py
#
# tokenizer for a simple expression evaluator for
# constraint rules
# ------------------------------------------------------------
import ply.lex as lex

# List of token names.   This is always required
reserved = {
	'COUNTU'		: 'COUNTU',
	'COUNT' 		: 'COUNT',
	'SUM' 			: 'SUM',
	'MAX' 			: 'MAX',
	'MIN' 			: 'MIN',
	'AVG'			: 'AVG',
	'STDEV' 		: 'STDEV',
	'TIME' 			: 'TIME',
	'TUMBLING'		: 'TUMBLING',
	'SLIDING'		: 'SLIDING',
	'IN'			: 'IN',
	'INTERNAL'		: 'INTERNAL',
	'BASE_TIME_GRANULARITY'	: 'BASE_TIME_GRANULARITY',
	'RESOURCES'		: 'RESOURCES',
	'EVENTTYPE'		: 'EVENTTYPE',
	'EVENTTIME'		: 'EVENTTIME',
	'RECEPTIONTIME'	: 'RECEPTIONTIME',
	'MAXDELAY'		: 'MAXDELAY',
	'FOREIGNKEY'	: 'FOREIGNKEY',
	'INHERIT'		: 'INHERIT',
	'INTEGER'		: 'INTEGER',
	'STRING'		: 'STRING',
	'FLOAT'			: 'FLOAT',
	'CAUSE'			: 'CAUSE',
	'START'			: 'START',
	'END' 			: 'END',
	'COUNT'			: 'COUNT',
	'BETWEEN'		: 'BETWEEN',
	'AND'			: 'AND',
	'EXACTLY' 		: 'EXACTLY',
	'TERMINATE'		: 'TERMINATE',
	'MICROSSECOND'		: 'MICROSSECOND',
	'SECOND'		: 'SECOND',
	'MINUTE'		: 'MINUTE',
	'HOUR'			: 'HOUR',
	'DAY'			: 'DAY',
	'FOR'			: 'FOR',
	'CREATE'		: 'CREATE',
	'DISTRIBUTION'	: 'DISTRIBUTION',
	'TABLES'		: 'TABLES',
	'VARIABLES'		: 'VARIABLES',
	'FUNCTIONS'		: 'FUNCTIONS',
	'INGESTTIME'	: 'INGESTTIME',
	'CHAR'			: 'CHAR',
	'ALL'			: 'ALL',
	'EventType'		: 'EVENTTYPE',
	'min'			: 'MINUTE',
	'hour'			: 'HOUR',
	'ms'			: 'MICROSECOND',
	'sec'			: 'SECOND',
	'day'			: 'DAY',
	'TIMECOUNT'		: 'TIMECOUNT',
	'AUTO_INCREMENT': 'AUTO_INCREMENT'
}

tokens = [
   'NUMBER',
   'LPAREN',
   'RPAREN',
   'LSPAREN',
   'RSPAREN',
   'ID',
   'COLON',
   'COMMA',
   'AT',
   'GT',
   'LT',
   'GTE',
   'LTE',
   'EQ',
   'FA',
   'BA',
   'PLUS',
   'MINUS',
   'SEMICOLON'
] + list(reserved.values())

# Regular expression rules for simple tokens
t_LPAREN  = r'\('
t_RPAREN  = r'\)'
t_COLON	  = r':'
t_SEMICOLON=r';'
t_COMMA	  = r','
t_AT	  = r'@'
t_GT	  = r'>'
t_LT	  = r'<'
t_GTE	  = r'>='
t_LTE	  = r'<='
t_EQ	  = r'='
t_FA	  = r'->'
t_BA	  = r'<-'
t_PLUS	  = r'\+'
t_MINUS	  = r'-'
t_LSPAREN = r'\['
t_RSPAREN = r'\]'
# A regular expression rule with some action code
def t_NUMBER(t):
    r'\d+'
    t.value = int(t.value)    
    return t

def t_ID(t):
    r'[a-zA-Z_][a-zA-Z_0-9]*'
    t.type = reserved.get(t.value,'ID')    # Check for reserved words
    return t

# Define a rule so we can track line numbers
def t_newline(t):
    r'\n+'
    t.lexer.lineno += len(t.value)

# A string containing ignored characters (spaces and tabs)
t_ignore  = ' \t'

# Error handling rule
def t_error(t):
    print("Illegal character '%s'" % t.value[0])
    t.lexer.skip(1)

t_ignore_COMMENT = r'\#.*'

# Build the lexer
lexer = lex.lex()

# Give the lexer some input
with open("./sample_data/bike_rental.txt") as f:
    lexer.input(f.read())


# Tokenize
while True:
    tok = lexer.token()
    if not tok: 
        break      # No more input
    print(tok)
