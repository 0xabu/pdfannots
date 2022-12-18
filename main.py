from tkinter import *
from tkinter import filedialog
from tkinter import messagebox
import os
from tkinter import ttk

class Main():
    def __init__(self):
        self.window = Tk()
        self.window.geometry("600x600")        
        self.button1 = Button(self.window, text='Upload PDF File', command=self.eventUpload)
        self.button2 = Button(self.window, text='Quit', command=self.eventQuit)
        self.button3 = Button(self.window, text='Save Output', command=self.eventSaveOutput)
        self.v = Scrollbar(self.window, orient='vertical')                     
        self.textArea = Text(self.window, yscrollcommand=self.v.set)        
        # self.text = Label(self.window, text="PDF File:")

    def show(self):
        self.v.pack(side=RIGHT, fill='y')   
        # self.text.pack(pady=10, side= TOP, anchor="w")
        self.button1.pack()        
        self.button3.pack()
        self.button2.pack()
        self.v.config(command=self.textArea.yview)
        self.textArea.pack()
        self.window.mainloop()

    def eventQuit(self):
        self.window.quit()

    def eventSaveOutput(self):        
        folder_selected = filedialog.askdirectory()                
        if (len(folder_selected) > 0):
            output_file = folder_selected + '/export.md'        
            if (len(self.textArea.get("1.0","end-1c"))>0):
                with open(output_file, 'w') as f:
                    f.write(self.textArea.get("1.0","end-1c"))
                messagebox.showinfo("pdfannots", "Sucess")
            else:
                messagebox.showwarning("pdfannots", "Choose a PDF File")
        else:
            messagebox.showwarning("pdfannots", "Choose a folder")

    def eventUpload(self):
        filename = filedialog.askopenfilename()        
        if (len(filename) > 0):
            extension = filename.split('.', 1)        
            if(extension[1] == 'pdf'):
                messagebox.showinfo("pdfannots", "Wait....")
                os.system("python pdfannots.py "+filename+" > export.md")
                messagebox.showinfo("pdfannots", "Sucess (export.md)")
                f = open("export.md", "r")
                for line in f:
                    self.textArea.insert(END, line)
                if os.path.exists("export.md"):
                    os.remove("export.md")
            else:
                messagebox.showwarning("pdfannots", "Choose a PDF file")
        else:
            messagebox.showwarning("pdfannots", "Choose a file")

if __name__ == '__main__':
    window = Main()
    window.show()
