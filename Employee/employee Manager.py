import sqlite3
from tkinter import *
from tkinter import messagebox
from tkinter import ttk
employee_list = []
def on_closing():
    if messagebox.askyesno("Confirmation", "Sure you want to exit?"):
        tk.destroy()  
    else:
        pass
def c_init():
    conn = sqlite3.connect('employee_track.db')
    return conn, conn.cursor()

def add_employee(id_entry,name_entry,salary_entry):
    try:
        id_val = id_entry.get().strip()
        name_val = name_entry.get().strip()
        salary_val = salary_entry.get().strip()
        with conn:
            c.execute("""INSERT INTO employee (id,name,salary) VALUES (?,?,?)""",(id_val,name_val,salary_val))
            global employee_list
            employee_list = [name[0] for name in c.execute("SELECT name FROM employee").fetchall()]
    
    except sqlite3.IntegrityError:
        messagebox.showerror("Error","Duplicate name")
        
def see_employee(view_employees):
    all_employees = c.execute("SELECT * FROM employee").fetchall()
    formatted_rows = [" | ".join(map(str, row)) for row in all_employees]
    view_employees.configure(text="\n".join(formatted_rows))

def edit_employee(click, salary1_entry, name1_entry):
    chosen = click.get().strip()
    new_salary = salary1_entry.get().strip()
    new_name = name1_entry.get().strip()
    
    with conn:
        if new_name != "" and new_salary != "":
            c.execute("UPDATE employee SET salary = ?, name = ? WHERE name = ?", (new_salary, new_name, chosen))
        elif new_salary == "":
            c.execute("UPDATE employee SET name = ? WHERE name = ?", (new_name, chosen))
        elif new_name == "":
            c.execute("UPDATE employee SET salary = ? WHERE name = ?", (new_salary, chosen))

    conn.commit()
def remove_employee(click):
    chosen = click.get().strip()
    exit_choice =  messagebox.askquestion("Confirm","Are you sure you want to delete?")
    if exit_choice == 'yes':
        with conn:
            c.execute("DELETE FROM employee WHERE name = ?", (chosen))
            conn.commit()
    else:
        pass
    
    

def gui():
    tk.title("Manage Employees")
    tk.geometry("500x400")
    Label(text = "Manage Employees",font = ("Helvetica",25)).pack(pady=5)
    notebook = ttk.Notebook(tk)
    add_tab = Frame(notebook)
    edit_tab = Frame(notebook)
    view_tab = Frame(notebook)
    notebook.add(add_tab, text="Add Employee")
    notebook.add(edit_tab, text="Edit Employees")
    notebook.add(view_tab, text="View Employees")
    notebook.pack(expand=1, fill='both')
    Label(add_tab, text="Employee ID").grid(row=0, column=0, padx=10, pady=10)
    Label(add_tab, text="Name").grid(row=1, column=0, padx=10, pady=10)
    Label(add_tab, text="Salary").grid(row=2, column=0, padx=10, pady=10)
    global id_entry, name_entry,salary_entry
    id_entry = Entry(add_tab)
    name_entry = Entry(add_tab)
    salary_entry = Entry(add_tab)
    id_entry.grid(row=0, column=1, padx=10, pady=10)
    name_entry.grid(row=1, column=1, padx=10, pady=10)
    salary_entry.grid(row=2, column=1, padx=10, pady=10)
    add_button = Button(add_tab,text="Confirm",command = lambda: add_employee(id_entry, name_entry,salary_entry)) .grid(row=3,column=0,pady=10)
    update_view = Button(view_tab,text = "Update Employee Data", command = lambda : see_employee(view_employees))
    update_view.pack(pady=5)
    employee_roles = Label(view_tab,text = "ID | name | salary",font = ("Helvetica",24))
    employee_roles.pack(pady=10)
    view_employees = Label(view_tab,font=("Helvetica",23))
    view_employees.pack(pady=10)
    click = StringVar()
    click.set("Select")
    OptionMenu(edit_tab, click , *employee_list ).grid(row = 3,column = 1,pady=10)
    Label(edit_tab, text="Change Name").grid(row=1, column=0, padx=10, pady=10)
    Label(edit_tab, text="Change Salary").grid(row=2, column=0, padx=10, pady=10)
    global name1_entry,salary1_entry
    name1_entry = Entry(edit_tab)
    salary1_entry = Entry(edit_tab)
    name1_entry.grid(row=1, column=1, padx=10, pady=10)
    salary1_entry.grid(row=2, column=1, padx=10, pady=10)
    remove_button = Button(edit_tab , text = "Remove Employee",command = lambda: remove_employee(click)).grid(row = 4, column = 1 , padx=5,pady=10)
    add_button1 = Button(edit_tab,text="Confirm Edit",command = lambda: edit_employee(click,salary1_entry,name1_entry)) .grid(row=4,column=0,pady=10)



if __name__ == '__main__':
    tk = Tk()
    tk.protocol("WM_DELETE_WINDOW",on_closing)
    conn, c = c_init()
    employee_list = [name[0] for name in c.execute("SELECT name FROM employee").fetchall()]
    c.execute("""
        CREATE TABLE IF NOT EXISTS employee (
            id INTEGER NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            salary INTEGER NOT NULL
            
        );
    """)
    gui()
    tk.mainloop()
    conn.close()
