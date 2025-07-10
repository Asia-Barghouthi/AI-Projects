import os
import datetime
import pandas as pd
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from smtplib import SMTP, SMTPException
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

data = pd.read_excel('dataDump.xlsx')

sessions = {}

logs = []


arabic_translations = {
    "welcome": "مرحبًا! يرجى اختيار لغتك:\n1. العربية\n2. الإنجليزية",
    "provide_id": "يرجى تقديم رقم الهوية الوطنية:",
    "multiple_sites": "لديك مواقع متعددة. يرجى اختيار واحد:",
    "verification_successful": "تم التحقق بنجاح. اختر خيارًا:\n1. خيارات الدفع\n2. معلومات العقد\n3. الاتصال بالوكيل\n4. إنهاء المحادثة",
    "invalid_id": "رقم الهوية الوطنية غير صحيح. يرجى المحاولة مرة أخرى.",
    "invalid_input": "إدخال غير صحيح. يرجى المحاولة مرة أخرى.",
    "payment_details": "تفاصيل الدفع:\n",
    "satisfaction_question": "هل أنت راضٍ عن الخدمة؟\n1. نعم\n2. لا",
    "thank_you": "شكرًا لتعليقاتك! وداعًا!"
}

def get_message(session, key):
    if session.get("language") == "Arabic":
        return arabic_translations[key]
    return {
        "welcome": "Welcome! Please select your language:\n1. Arabic\n2. English",
        "provide_id": "Please provide your National ID:",
        "multiple_sites": "You have multiple sites. Please select one:",
        "verification_successful": "Verification successful. Select an option:\n1. Payment Options\n2. Contract Info\n3. Call to Agent\n4. Exit Chat",
        "invalid_id": "Invalid National ID. Please try again.",
        "invalid_input": "Invalid input. Please try again.",
        "payment_details": "Payment Details:\n",
        "satisfaction_question": "Are you satisfied with the service?\n1. Yes\n2. No",
        "thank_you": "Thank you for your feedback! Goodbye!"
    }[key]

@app.route('/webhook', methods=['POST'])
def webhook():
    incoming_msg = request.values.get('Body', '').strip()
    from_number = request.values.get('From', '').strip()
    response = MessagingResponse()

    if from_number not in sessions:
        sessions[from_number] = {
            'step': 'language_selection',
            'start_time': datetime.datetime.now(),
            'verified': False,
            'attempts': 0,
            'satisfaction': None,
            'actions': []
        }
        response.message(get_message(sessions[from_number], "welcome"))
        return str(response)

    session = sessions[from_number]
    step = session['step']

    if step == 'language_selection':
        if incoming_msg in ['1', '2']:
            session['language'] = 'Arabic' if incoming_msg == '1' else 'English'
            session['step'] = 'request_id'
            response.message(get_message(session, "provide_id"))
        else:
            response.message(get_message(session, "welcome"))

    elif step == 'request_id':
        session['attempts'] += 1
        kpi_data['verification_attempts'] += 1
        try:
            national_id = int(incoming_msg)
            matched_data = data[data['National Id'] == national_id]

            if not matched_data.empty:
                session['verified'] = True
                session['national_id'] = national_id
                kpi_data['successful_verifications'] += 1
                kpi_data['unique_users'].add(from_number)

                if len(matched_data) > 1:
                    session['step'] = 'select_site'
                    site_list = "\n".join([f"{i + 1}. {row['SiteName']}" for i, row in matched_data.iterrows()])
                    response.message(f"{get_message(session, 'multiple_sites')}\n{site_list}")
                else:
                    session['selected_site'] = matched_data.iloc[0]
                    session['step'] = 'menu'
                    response.message(get_message(session, "verification_successful"))
            else:
                if session['attempts'] >= 3:
                    response.message(get_message(session, "invalid_id"))
                    del sessions[from_number]
                else:
                    response.message(get_message(session, "invalid_id"))
        except ValueError:
            response.message(get_message(session, "invalid_input"))

    elif step == 'select_site':
        try:
            selected_index = int(incoming_msg) - 1
            matched_data = data[data['National Id'] == session['national_id']]

            if 0 <= selected_index < len(matched_data):
                session['selected_site'] = matched_data.iloc[selected_index]
                session['step'] = 'menu'
                response.message(get_message(session, "verification_successful"))
            else:
                response.message(get_message(session, "invalid_input"))
        except ValueError:
            response.message(get_message(session, "invalid_input"))

    elif step == 'menu':
        if incoming_msg == '1':
            session['step'] = 'menu'
            site_data = session['selected_site']
            payment_details = get_message(session, "payment_details")
            payment_details += f"Payment Status: {site_data['IsPaymentIssued']}\n"
            payment_details += f"Payment Value: {site_data['Portion']}\n"
            payment_details += f"Payment Method: {site_data['Payment Method']}\n"
            payment_details += f"Payment Issued Means: {site_data['IssueType']}\n"
            payment_details += f"Payment Made To: {site_data['whereToRecieve']}\n"
            response.message(payment_details)
        elif incoming_msg == '2':
            contract_data = session['selected_site'][['ContractEndDate', 'ContractRenewalDate']]
            contract_message = "Contract Info:\n"
            if not pd.isnull(contract_data['ContractRenewalDate']):
                contract_message += f"Renewal Date: {contract_data['ContractRenewalDate']}\n"
            if not pd.isnull(contract_data['ContractEndDate']):
                contract_message += f"End Date: {contract_data['ContractEndDate']}\n"
            response.message(contract_message)
        elif incoming_msg == '3':
            kpi_data['escalation_count'] += 1
            response.message("Contact Number: +962 7 7010 7000")
        elif incoming_msg == '4':
            session['step'] = 'satisfaction'
            response.message(get_message(session, "satisfaction_question"))
        else:
            response.message(get_message(session, "verification_successful"))

    elif step == 'satisfaction':
        if incoming_msg in ['1', '2']:
            session['satisfaction'] = 'Satisfied' if incoming_msg == '1' else 'Not Satisfied'
            kpi_data['satisfied_users'] += 1 if incoming_msg == '1' else 0
            response.message(get_message(session, "thank_you"))
            del sessions[from_number]
        else:
            response.message(get_message(session, "satisfaction_question"))

    return str(response)


if __name__ == '__main__':
    app.run(debug=True)
   
 
