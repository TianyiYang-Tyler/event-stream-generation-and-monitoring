import ply.yacc as yacc
from cepalex import tokens
import xmltodict

start = 'cepal_construct'

# =========================
# Helpers (optional but clean)
# =========================
def make_list(p, idx):
    return [p[idx]]


# =========================
# Top-level
# =========================

def p_cepal_construct(p):
    '''
    cepal_construct : global_configurations event_type_definitions process_schema event_distributions
    '''
    p[0] = {
        "global_configurations": p[1],
        "event_type_definitions": p[2],
        "process_schema": p[3],
        "event_distributions": p[4]
    }


# =========================
# Global Configurations
# =========================

def p_global_configurations(p):
    '''
    global_configurations : base_time_granularity time_range optional_resource
    '''
    p[0] = {
        "base_time_granularity": p[1],
        "time_range": p[2],
        "optional_resource": p[3]
    }


def p_base_time_granularity(p):
    '''
    base_time_granularity : BASE_TIME_GRANULARITY EQ NUMBER time_unit
    '''
    p[0] = {
        "value": p[3],
        "unit": p[4]
    }


def p_time_range(p):
    '''
    time_range : START EQ time_val COMMA END EQ time_val
    '''
    p[0] = {
        "start_time": p[3],
        "end_time": p[7]
    }


def p_time_val(p):
    '''
    time_val : NUMBER time_unit
             | NUMBER
    '''
    if len(p) == 3:
        p[0] = {"value": p[1], "unit": p[2]}
    else:
        p[0] = {"value": p[1], "unit": "DEFAULT"}


def p_time_unit(p):
    '''
    time_unit : MICROSSECOND
              | SECOND
              | MINUTE
              | HOUR
              | DAY
    '''
    p[0] = p[1]


# =========================
# Resources
# =========================

def p_optional_resource(p):
    '''
    optional_resource : RESOURCES TABLES table_resources VARIABLES variables FUNCTIONS custom_functions
    '''
    p[0] = {
        "table_resources": p[3],
        "variables": p[5],
        "functions": p[7]
    }


def p_table_resources(p):
    '''
    table_resources : ID COMMA table_resources
                    | END TABLES
    '''
    if len(p) == 3:
        p[0] = []
    else:
        p[0] = [p[1]] + p[3]


def p_variables(p):
    '''
    variables : value_bound COMMA variables
              | END VARIABLES
    '''
    if len(p) == 3:
        p[0] = []
    else:
        p[0] = [p[1]] + p[3]


def p_value_bound(p):
    '''
    value_bound : ID EQ LPAREN values COMMA values RPAREN
    '''
    p[0] = {
        "variable_name": p[1],
        "lower_bound_val": p[4],
        "upper_bound_val": p[6]
    }


# =========================
# Values / Numbers
# =========================

def p_values(p):
    '''
    values : NUMBER
           | LSPAREN numbers RSPAREN
    '''
    p[0] = p[1] if len(p) == 2 else p[2]


def p_numbers(p):
    '''
    numbers : numbers COMMA NUMBER
            | NUMBER
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[3]]


# =========================
# Functions
# =========================

def p_custom_functions(p):
    '''
    custom_functions : ID COMMA custom_functions
                     | END FUNCTIONS
    '''
    if len(p) == 3:
        p[0] = []
    else:
        p[0] = [p[1]] + p[3]


# =========================
# Event Type Definitions
# =========================

def p_event_type_definitions(p):
    '''
    event_type_definitions : event_type_definitions event_type_definition
                           | event_type_definition
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[2]]


def p_event_type_definition(p):
    '''
    event_type_definition : CREATE EVENTTYPE ID LPAREN EVENTTIME NUMBER COMMA INGESTTIME LPAREN NUMBER RPAREN MAXDELAY LPAREN NUMBER RPAREN COMMA attributes COMMA functional_dependencies RPAREN
    '''
    p[0] = {
        "event_name": p[3],
        "event_time": p[6],
        "reception_time": p[10],
        "max_delay": p[14],
        "attributes": p[17],
        "functional_dependencies": p[19]
    }


# =========================
# Functional Dependencies
# =========================

def p_functional_dependencies(p):
    '''
    functional_dependencies : source_event_list FA target_event_list

    '''
    p[0] = {
        "source_events": p[1],
        "target_events": p[3]
    }

def p_source_event_list(p):
    '''
    source_event_list   : LPAREN event_list RPAREN
                        | ID
    '''
    if len(p) == 2:
        p[0] = p[1]
    else:
        p[0] = p[2]

def p_target_event_list(p):
    '''
    target_event_list   : LPAREN event_list RPAREN
                        | ID
                        | ALL
    '''
    if len(p) == 2:
        p[0] = p[1]
    else:
        p[0] = p[2]

# =========================
# Attributes
# =========================

def p_attributes(p):
    '''
    attributes : attributes COMMA attribute
               | attribute
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[3]]


def p_attribute(p):
    '''
    attribute : ID COLON attribute_type
    '''
    p[0] = {
        "attribute_name": p[1],
        "attribute_type": p[3]
    }


def p_attribute_type(p):
    '''
    attribute_type : global_restricted
                   | table_reference
                   | event_reference
                   | raw_value
    '''
    p[0] = p[1]


def p_global_restricted(p):
    '''
    global_restricted : IN ID
    '''
    p[0] = {
        "type": "global_restricted",
        "bound_variable": p[2]
    }


def p_table_reference(p):
    '''
    table_reference : ID LPAREN table_values RPAREN FOREIGNKEY
                    | ID LPAREN table_values RPAREN
    '''
    p[0] = {
        "type": "table_reference",
        "table_name": p[1],
        "table_values": p[3],
        "is_foreign_key": len(p) == 6
    }


def p_table_values(p):
    '''
    table_values : table_values COMMA ID
                  | ID
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[3]]


def p_event_reference(p):
    '''
    event_reference : INHERIT ID LPAREN event_values RPAREN FOREIGNKEY
                    | INHERIT ID LPAREN event_values RPAREN
    '''
    p[0] = {
        "type": "event_reference",
        "event_name": p[2],
        "event_values": p[4],
        "is_foreign_key": len(p) == 6
    }


def p_event_values(p):
    '''
    event_values : event_values COMMA ID
                 | ID
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[3]]


def p_raw_value(p):
    '''
    raw_value : INTEGER
              | STRING
              | FLOAT
              | CHAR LPAREN NUMBER RPAREN
    '''
    p[0] = {
        "type": "raw_value",
        "value": p[1]
    }
    if len(p) > 3:
        p[0]['length'] = p[3]


# =========================
# Process Schema
# =========================

def p_process_schema(p):
    '''
    process_schema : start_rule rules
    '''
    p[0] = [p[1]] + p[2]


def p_start_rule(p):
    '''
    start_rule : ID COLON CAUSE START SEMICOLON target_event
    '''
    p[0] = {
        "rule_id": p[1],
        "type": "START",
        "target_events": p[6]
    }


def p_target_event(p):
    '''
    target_event : ID time_condition count_condition
    '''
    p[0] = {
        "event_name": p[1],
        "time_condition": p[2],
        "count_condition": p[3]
    }


# =========================
# Conditions
# =========================

def p_time_condition(p):
    '''
    time_condition : TIME BETWEEN time_val AND time_val
                   | TIME EXACTLY time_val
                   | empty
    '''
    if len(p) == 2:
        p[0] = None
    elif len(p) == 4:
        p[0] = {"type": "EXACTLY", "time": p[3]}
    else:
        p[0] = {"type": "RANGE", "start_time": p[3], "end_time": p[5]}


def p_count_condition(p):
    '''
    count_condition : COUNT BETWEEN time_val AND time_val
                    | COUNT EXACTLY time_val
                    | empty
    '''
    if len(p) == 2:
        p[0] = None
    elif len(p) == 4:
        p[0] = {"type": "EXACTLY", "count": p[3]}
    else:
        p[0] = {"type": "RANGE", "start_count": p[3], "end_count": p[5]}


# =========================
# Rules
# =========================

def p_rules(p):
    '''
    rules : rules causation_rule
          | rules termination_rule
          | causation_rule
          | termination_rule
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[2]]


def p_causation_rule(p):
    '''
    causation_rule : ID COLON CAUSE event_list SEMICOLON target_event
    '''
    p[0] = {
        "rule_id": p[1],
        "type": "CAUSE",
        "source_events": p[4],
        "target_event": p[6]
    }


def p_event_list(p):
    '''
    event_list : ID COMMA event_list
               | ID
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = [p[1]] + p[3]


def p_termination_rule(p):
    '''
    termination_rule : TERMINATE ID
                     | TERMINATE ID SEMICOLON event_list
    '''
    p[0] = {
        "source_events": p[1],
        "type": "TERMINATE",
        "target_event": "ALL" if len(p) == 3 else p[4]
    }


# =========================
# Event Distributions
# =========================

def p_event_distributions(p):
    '''
    event_distributions : count_distribution event_distributions
                        | time_distribution event_distributions
                        | END
    '''
    if len(p) == 2:
        p[0] = []
    else:
        p[0] = [p[1]] + p[2]


def p_time_distribution(p):
    '''
    time_distribution : CREATE TIME DISTRIBUTION FOR ID LPAREN BASE_TIME_GRANULARITY EQ time_val COMMA distribution_list RPAREN
    '''
    p[0] = {
        "type": "time_distribution",
        "rule_id": p[5],
        "base_time_granularity_value": p[9],
        "distribution": p[11]
    }


def p_count_distribution(p):
    '''
    count_distribution : CREATE COUNT DISTRIBUTION FOR ID LPAREN distribution_list RPAREN
    '''
    p[0] = {
        "type": "count_distribution",
        "rule_id": p[5],
        "distribution": p[7]
    }


def p_distribution_list(p):
    '''
    distribution_list : distribution COMMA distribution_list
                      | distribution
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = [p[1]] + p[3]


def p_distribution(p):
    '''
    distribution : distribution_range COLON NUMBER
    '''
    p[0] = {
        "distribution_range": p[1],
        "value": p[3]
    }


def p_distribution_range(p):
    '''
    distribution_range : LSPAREN NUMBER COMMA NUMBER RPAREN
    '''
    p[0] = {
        "start": p[2],
        "end": p[4]
    }


# =========================
# Empty + Error
# =========================

def p_empty(p):
    'empty :'
    p[0] = None


def p_error(p):
    print(f"Syntax error at {p}")

# Build the parser
parser = yacc.yacc()

result = ''
with open("sample_data/bike_rental.txt") as f:
    result = parser.parse(f.read())

data = {'root': result}
with open("output_xml/bike_rental_info.xml", "w") as file:
    xmltodict.unparse(data, output=file, pretty=True)
