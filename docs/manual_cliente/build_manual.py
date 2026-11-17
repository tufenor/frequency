from pathlib import Path
import os
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
ROOT=Path(r'C:\Users\tufen\Documents\frequency'); OUT=Path(os.environ.get('FREQUENCY_MANUAL_OUTPUT', str(ROOT/'docs'/'manual_cliente'))); OUT.mkdir(parents=True,exist_ok=True)
font=str(Path(r'C:\Windows\Fonts\segoeui.ttf')); bold=str(Path(r'C:\Windows\Fonts\segoeuib.ttf'))
def F(n,b=False): return ImageFont.truetype(bold if b else font,n)
NAVY=(14,31,24); GREEN=(28,67,48); LIME=(190,241,82); CREAM=(247,249,244); WHITE=(255,255,255); MUTED=(93,110,102); BORDER=(222,230,222); RED=(185,70,62); BLUE=(59,119,181)
def rr(d,b,r,fill,outline=None,w=1): d.rounded_rectangle(b,radius=r,fill=fill,outline=outline,width=w)
def cover_art():
 im=Image.new('RGB',(1400,620),NAVY); d=ImageDraw.Draw(im)
 d.ellipse((870,-180,1470,430),fill=(26,60,43)); d.ellipse((1040,80,1350,390),fill=(43,83,53))
 d.text((70,72),'FREQUENCY GYM',font=F(42,1),fill=LIME); d.text((74,132),'Gestión clara para academias que quieren crecer',font=F(24),fill=(220,234,219))
 rr(d,(74,220,780,540),24,(247,249,244),outline=(190,241,82),w=3); d.rectangle((112,260,742,474),fill=(226,235,223)); d.rectangle((112,260,742,300),fill=NAVY); d.ellipse((136,274,150,288),fill=(255,115,106)); d.ellipse((160,274,174,288),fill=(255,205,86)); d.ellipse((184,274,198,288),fill=LIME); d.text((228,269),'Panel de control',font=F(16,1),fill=WHITE)
 for i,h in enumerate([92,140,112,168,126]): d.rounded_rectangle((154+i*105,420-h,202+i*105,420),radius=10,fill=GREEN); d.ellipse((154+i*105,402-h,202+i*105,450-h),fill=LIME)
 d.text((130,496),'Alumnos  ·  Pagos  ·  Accesos',font=F(18,1),fill=NAVY)
 d.ellipse((1040,168,1210,338),fill=(236,182,142)); d.ellipse((1075,125,1175,230),fill=(247,194,153)); d.arc((1090,185,1160,245),0,180,fill=NAVY,width=5); d.arc((1065,100,1190,240),180,350,fill=NAVY,width=18); d.rounded_rectangle((985,320,1270,560),radius=70,fill=GREEN); d.rounded_rectangle((1035,350,1220,450),radius=24,fill=(38,89,60)); d.text((1076,382),'Tu equipo',font=F(22,1),fill=LIME); d.text((1010,500),'Operación bajo control',font=F(19,1),fill=WHITE)
 im.save(OUT/'00_capa.png')
cover_art()
def screen(fn,title,sub,active,stats):
 im=Image.new('RGB',(1200,700),CREAM); d=ImageDraw.Draw(im); d.rectangle((0,0,230,700),fill=NAVY); d.text((38,32),'FREQUENCY',font=F(27,1),fill=LIME); d.text((38,68),'Gestión de gimnasios',font=F(15),fill=(200,219,202))
 nav=['Inicio','Alumnos','Planes y pagos','Acceso','Reportes','Integraciones','Copias de seguridad']; y=132
 for it in nav:
  if it==active: rr(d,(20,y-8,210,y+34),12,GREEN)
  d.ellipse((40,y+3,54,y+17),fill=LIME if it==active else (121,146,129)); d.text((68,y),it,font=F(16,it==active),fill=WHITE if it==active else (194,211,198)); y+=55
 d.text((270,44),title,font=F(34,1),fill=NAVY); d.text((270,88),sub,font=F(17),fill=MUTED); d.line((270,124,1155,124),fill=BORDER,width=2)
 x=270; y=156
 for a,b,c in stats:
  rr(d,(x,y,x+260,y+122),16,WHITE,BORDER,2); d.text((x+20,y+18),a,font=F(16),fill=MUTED); d.text((x+20,y+49),b,font=F(28,1),fill=c); d.text((x+20,y+91),'Actualizado ahora',font=F(13),fill=MUTED); x+=290
 rr(d,(270,330,1155,650),18,WHITE,BORDER,2); d.text((300,360),'Área de trabajo',font=F(20,1),fill=NAVY)
 for i in range(4):
  yy=410+i*48; rr(d,(302,yy,1105,yy+30),8,(243,247,241)); d.rectangle((316,yy+8,470,yy+22),fill=(181,204,185)); d.rectangle((520,yy+8,720,yy+22),fill=(218,228,218)); d.rectangle((770,yy+8,1040,yy+22),fill=(218,228,218))
 if active=='Alumnos':
  d.text((300,400),'Alumno',font=F(14,1),fill=MUTED); d.text((620,400),'Plan',font=F(14,1),fill=MUTED); d.text((850,400),'Estado',font=F(14,1),fill=MUTED)
  for i,(name,plan,state) in enumerate([('María López','Profesional','Activo'),('Gabriel Pereira','Premium','Activo'),('Ana Torres','Essencial','Pendiente')]):
   yy=432+i*58; d.ellipse((304,yy,344,yy+40),fill=(184,220,144)); d.text((360,yy+9),name,font=F(15,1),fill=NAVY); d.text((620,yy+9),plan,font=F(14),fill=MUTED); rr(d,(850,yy+5,960,yy+35),12,(231,245,210) if state=='Activo' else (255,241,211)); d.text((870,yy+11),state,font=F(12,1),fill=GREEN if state=='Activo' else (143,103,29))
 elif active=='Planes y pagos':
  d.text((300,405),'Calendario de vencimientos',font=F(16,1),fill=NAVY)
  for i in range(6):
   x=300+(i%3)*245; y=442+(i//3)*66; rr(d,(x,y,x+210,y+48),10,(242,247,239),BORDER); d.text((x+14,y+8),f'{10+i:02d}/10/2026',font=F(13,1),fill=NAVY); d.text((x+14,y+28),'Bs 250,00',font=F(12),fill=GREEN)
 elif active=='Acceso':
  rr(d,(300,405,560,560),18,(229,246,213),outline=LIME,w=3); d.ellipse((380,430,480,530),fill=GREEN); d.text((411,451),'✓',font=F(55,1),fill=LIME); d.text((354,540),'ACCESO LIBERADO',font=F(16,1),fill=GREEN); rr(d,(650,405,1100,560),18,(250,242,236),outline=(232,205,195),w=2); d.text((680,430),'Último intento',font=F(15,1),fill=NAVY); d.text((680,465),'Rostro no identificado',font=F(20,1),fill=RED); d.text((680,505),'Revise plan y fotos del alumno',font=F(13),fill=MUTED)
 elif active=='Reportes':
  d.text((300,405),'Asistencia por semana',font=F(16,1),fill=NAVY); d.line((320,575,1060,575),fill=BORDER,width=2)
  for i,h in enumerate([74,112,88,145,126,170,152]): d.rounded_rectangle((345+i*95,575-h,390+i*95,575),radius=8,fill=LIME if i in (3,5) else (112,157,83)); d.text((345+i*95,590),f'S{i+1}',font=F(11),fill=MUTED)
 elif active=='Integraciones':
  for i,(name,state) in enumerate([('Cámara de seguridad','Conectada'),('YouTube','Premium activo'),('Gmail de cobros','Pendiente')]):
   x=300+(i%2)*390; y=408+(i//2)*86; rr(d,(x,y,x+350,y+62),12,(243,248,239),BORDER); d.ellipse((x+16,y+16,x+42,y+42),fill=LIME if state!='Pendiente' else (244,193,83)); d.text((x+58,y+11),name,font=F(14,1),fill=NAVY); d.text((x+58,y+34),state,font=F(12),fill=MUTED)
 elif active=='Copias de seguridad':
  d.text((300,405),'Historial de copias',font=F(16,1),fill=NAVY)
  for i,label in enumerate(['Hoy · 03:00','Ayer · 03:00','Lun · 03:00']):
   y=445+i*55; d.ellipse((310,y,330,y+20),fill=LIME); d.line((320,y+20,320,y+45),fill=(160,193,132),width=3); d.text((350,y),label,font=F(14,1),fill=NAVY); d.text((650,y),'Completada · cifrada',font=F(13),fill=MUTED)
 elif active=='YouTube':
  d.text((300,405),'Cola de reproducción',font=F(16,1),fill=NAVY)
  for i,name in enumerate(['Entrenamiento 2026','Cardio motivación','Fuerza y enfoque']):
   y=445+i*55; rr(d,(310,y,1080,y+36),9,(242,247,239)); d.ellipse((325,y+8,345,y+28),fill=LIME if i==0 else (171,200,151)); d.text((365,y+8),name,font=F(14,1 if i==0 else 0),fill=NAVY)
 im.save(OUT/(fn + '.png'))
for args in [('01_inicio','Inicio','Resumen de la academia','Inicio',[('Alumnos activos','128',GREEN),('Entradas hoy','74',BLUE),('Pagos pendientes','6',RED)]),('02_alumnos','Alumnos','Gestiona tus alumnos','Alumnos',[('Total','128',GREEN),('Activos','116',BLUE),('Sin plan','12',RED)]),('03_planes','Planes y pagos','Crea planes y controla vencimientos','Planes y pagos',[('Ingresos','Bs 18.450',GREEN),('Pagados','112',BLUE),('Pendientes','16',RED)]),('04_acceso','Acceso','Control de entradas y presencia','Acceso',[('Entradas','74',GREEN),('Permitidas','69',BLUE),('Bloqueadas','5',RED)]),('05_reportes','Reportes','Indicadores para decidir mejor','Reportes',[('Retención','86%',GREEN),('Asistencia','72%',BLUE),('Conversión','34%',LIME)]),('06_integraciones','Integraciones','Cámara, YouTube y correo','Integraciones',[('Cámara','Conectada',GREEN),('YouTube','Premium',BLUE),('Gmail','En revisión',RED)]),('07_backup','Copias de seguridad','Protege y recupera los datos','Copias de seguridad',[('Última copia','Hoy 03:00',GREEN),('Destino','Google Drive',BLUE),('Estado','Seguro',LIME)])]: screen(*args)
# simple special screens
im=Image.new('RGB',(1200,700),CREAM); d=ImageDraw.Draw(im); d.rectangle((0,0,230,700),fill=NAVY); d.text((38,32),'FREQUENCY',font=F(27,1),fill=LIME); d.text((38,68),'Registro facial',font=F(15),fill=(200,219,202)); d.text((270,44),'Captura facial',font=F(34,1),fill=NAVY); d.text((270,88),'Tres ángulos para mejorar el reconocimiento',font=F(17),fill=MUTED); rr(d,(270,145,820,630),20,WHITE,BORDER,2); d.text((300,173),'Posicione el rostro dentro del marco',font=F(19,1),fill=NAVY); rr(d,(350,220,740,545),18,(236,242,234),LIME,4); d.ellipse((445,280,645,480),outline=GREEN,width=5); d.arc((500,340,590,420),0,180,fill=GREEN,width=4); d.line((480,460,610,460),fill=GREEN,width=4); d.text((408,570),'Frontal  •  Perfil izquierdo  •  Perfil derecho',font=F(15),fill=MUTED); rr(d,(860,330,1120,405),14,GREEN); d.text((900,355),'Capturar foto',font=F(18,1),fill=WHITE); im.save(OUT/'08_captura_facial.png')
# YouTube screen based on the same visual language
screen('09_youtube','YouTube','Busca música dentro de Frequency','YouTube',[('Estado','Premium',GREEN),('Cola','8 videos',BLUE),('Reproducción','En pausa',RED)])
# docx
D=Document(); s=D.sections[0]; s.page_width=Inches(8.27); s.page_height=Inches(11.69); s.top_margin=Inches(.65); s.bottom_margin=Inches(.65); s.left_margin=Inches(.75); s.right_margin=Inches(.75); D.styles['Normal'].font.name='Aptos'; D.styles['Normal'].font.size=Pt(10); D.styles['Normal'].font.color.rgb=RGBColor(45,63,53); D.styles['Title'].font.name='Aptos Display'; D.styles['Title'].font.color.rgb=RGBColor(28,67,48); D.styles['Heading 1'].font.name='Aptos Display'; D.styles['Heading 1'].font.size=Pt(24); D.styles['Heading 1'].font.color.rgb=RGBColor(28,67,48); D.styles['Heading 2'].font.name='Aptos'; D.styles['Heading 2'].font.size=Pt(14); D.styles['Heading 2'].font.color.rgb=RGBColor(76,112,49)
footer=s.footer.paragraphs[0]; footer.alignment=WD_ALIGN_PARAGRAPH.CENTER; footer.add_run('Frequency Gym  •  Manual para propietarios  •  frequencygym.tech').font.size=Pt(8)
def bullets(items):
 for x in items: D.add_paragraph(x,style='List Bullet')
def section(title,img,desc,steps):
 D.add_heading(title,1); D.add_picture(str(OUT/img),width=Inches(6.7)); p=D.add_paragraph('Figura orientativa de '+title.lower()+'.'); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.runs[0].italic=True; p.runs[0].font.size=Pt(8); D.add_paragraph(desc); D.add_heading('Cómo usarla',2); bullets(steps)
p=D.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.add_run().add_picture(str(ROOT/'frequency-logo-whatsapp.png'),width=Inches(1.2)); p=D.add_paragraph(style='Title'); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.add_run('Manual de uso de Frequency Gym'); p=D.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.add_run('Guía institucional para propietarios y administradores').font.size=Pt(17); D.add_picture(str(OUT/'00_capa.png'),width=Inches(6.7)); p=D.add_paragraph('Una operación más clara, una academia más fuerte.'); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.runs[0].bold=True; p.runs[0].font.color.rgb=RGBColor(76,112,49); D.add_paragraph('Frequency Gym reúne alumnos, planes, pagos, accesos e indicadores en un solo lugar. Este manual acompaña a su equipo desde la configuración inicial hasta la operación diaria, con instrucciones claras y referencias visuales de cada módulo.'); D.add_heading('Antes de comenzar',1); bullets(['Use la cuenta del propietario para configuraciones sensibles.','Mantenga actualizados planes, vencimientos y contactos.','Las funciones Premium dependen del plan contratado.','Puede cambiar el idioma desde el selector del sistema.']); D.add_page_break(); D.add_heading('Índice',1); bullets(['Inicio y estado de la academia','Alumnos','Planes y pagos','Acceso y presencia','Captura facial opcional','Reportes','Integraciones Premium','Copias de seguridad','Roles y permisos','Mantenimiento y ayuda']); D.add_page_break()
section('Inicio','01_inicio.png','La pantalla resume la operación diaria de la academia.', ['Revise alumnos activos, entradas y pagos pendientes.','Abra una tarjeta para ir al módulo correspondiente.','Use el menú lateral para cambiar de área.'])
section('Alumnos','02_alumnos.png','Aquí se crean, editan y consultan los perfiles, incluyendo foto, teléfono, plan y estado.', ['Registre un alumno aunque todavía no tenga plan.','Use Editar alumno para sustituir una foto o tomar una nueva.','Guarde los cambios y revise el estado del perfil.'])
section('Planes y pagos','03_planes.png','El propietario administra planes, vencimientos y estados de pago.', ['Cree o edite planes con precio y duración.','Asigne el plan desde la ficha del alumno.','Registre pagos y revise vencimientos futuros.','Solo el propietario puede eliminar pagos ya registrados como pagados.'])
section('Acceso','04_acceso.png','El monitor muestra en tiempo real si una entrada fue permitida o bloqueada.', ['Verifique lector y conexión.','Revise nombre, foto, plan y vencimiento.','Un alumno sin plan activo debe recibir acceso bloqueado.','Consulte el historial de presencia.'])
section('Captura facial opcional','08_captura_facial.png','La biometría facial complementa los demás métodos de acceso.', ['Solicite autorización al alumno.','Capture frontal, perfil izquierdo y perfil derecho.','Confirme que las tres fotos aparezcan antes de guardar.','Si la cámara falla, revise permisos, HTTPS y otras aplicaciones que puedan usarla.'])
section('Reportes','05_reportes.png','Los reportes ayudan a entender asistencia, retención, pagos y crecimiento.', ['Filtre por período, plan o estado.','Use los datos para detectar renovaciones y alumnos en riesgo.','Compare asistencia y pagos antes de tomar decisiones.'])
section('Integraciones Premium','06_integraciones.png','Las integraciones se activan según el plan contratado.', ['Conecte cámara, YouTube o correo desde el módulo.','Revise los permisos solicitados antes de autorizar.','Use el correo de la academia para leer comprobantes de pago.','YouTube permanece dentro de Frequency y permite buscar y añadir videos a la cola.'])
section('Copias de seguridad','07_backup.png','Las copias protegen la base de datos y facilitan la recuperación.', ['Elija una carpeta local independiente de OneDrive personal.','Use Hacer copia ahora para una copia manual.','Configure la rutina automática diaria o semanal.','Pruebe una restauración en un entorno de prueba.'])
section('YouTube','09_youtube.png','El reproductor funciona dentro de Frequency y mantiene la cola en segundo plano.', ['Busque por nombre de canción o artista.','Use Reproducir para iniciar y Añadir a cola para guardar.','Los siguientes videos comienzan cuando termina el actual.','Si un video está bloqueado o no disponible, elija otro.'])
D.add_heading('Roles y permisos',1); D.add_paragraph('El propietario controla configuraciones sensibles; el equipo opera las tareas permitidas. La eliminación de pagos pagados queda reservada al propietario.'); t=D.add_table(rows=1,cols=2); t.alignment=WD_TABLE_ALIGNMENT.CENTER; t.style='Table Grid'; t.rows[0].cells[0].text='Rol'; t.rows[0].cells[1].text='Responsabilidades';
for a,b in [('Propietario','Academia, planes, pagos, equipo, integraciones, copias y pagos pagados.'),('Equipo','Alumnos, presencia y operaciones autorizadas.'),('Monitor','Registro de entradas y resultado de acceso.')]: c=t.add_row().cells; c[0].text=a; c[1].text=b
D.add_heading('Mantenimiento y ayuda',1); bullets(['Revise entradas bloqueadas y pagos pendientes cada día.','Confirme que lectores, cámara y copias estén conectados.','Si la cámara está ocupada, cierre otras aplicaciones.','Si un video falla, pruebe otro contenido de YouTube.','Use el WhatsApp o el correo configurado para soporte.'])
out=OUT/'Manual_Frequency_Gym_Propietarios.docx'; D.save(out); print(out)
