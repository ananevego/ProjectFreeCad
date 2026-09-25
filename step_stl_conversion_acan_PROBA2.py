# Convert STEP files to STL using GMSH
import gmsh
from pathlib import Path
import os
import sys

# --- CONFIG
ROOT_DIR = Path(__file__).parent
INPUT_PATH = ROOT_DIR / "step_files"
OUTPUT_PATH = ROOT_DIR / "stl_files"

# ---


def scan_directory(INPUT_PATH):
  for _,dirs, files in os.walk(INPUT_PATH):
    for dir in dirs:
             print(f"Поддиректория: {dir}")
             print(f"ПУТЬ: {INPUT_PATH}\{dir}")
             dir_step = os.path.join(INPUT_PATH, dir)             
             dir_stl = os.path.join(OUTPUT_PATH, dir)
             print(dir_step)
             print(dir_stl)      
          
     
             if not os.path.exists(dir_stl): os.makedirs(dir_stl)
                       

             #print(f" -> ERROR: ДИРРЕКТОРИЯ РАНЕЕ УЖЕ СОЗДАНА")
          # for file in files:
             
             files = [f for f in os.listdir(dir_step) if f.lower().endswith(('.step', '.stp'))]
             print(f"--- START GMSH CONVERSION ({len(files)}) ---")

             gmsh.initialize()
             gmsh.option.setNumber("General.Terminal", 1)
  
          #for filename in files1:
             #print(f"Converting: {filename}...")
     
             for files1 in files:
                  try:
                     input_file = os.path.join(dir_step, files1)
                     print(input_file)
                     output_file = os.path.join(dir_stl, os.path.splitext(files1)[0] + ".stl")
                     print(input_file)
                     print(output_file)
         
            # Clear previous model
                     gmsh.clear()
            
            # Load STEP file
                     gmsh.merge(input_file)
            
            # Meshing settings
            # Mesh.Algorithm 6 = Frontal-Delaunay (triangular)
            #gmsh.option.setNumber("Mesh.Algorithm", 4)
                     gmsh.option.setNumber("Mesh.Algorithm", 6)
            # Mesh size (smaller value = finer mesh/more detail)
                     gmsh.option.setNumber("Mesh.MeshSizeMin", 0.01)
                     gmsh.option.setNumber("Mesh.MeshSizeMax", 0.5)
                     gmsh.option.setNumber("Mesh.MeshSizeFromPoints",0)
                     gmsh.option.setNumber("Mesh.CharacteristicLengthMax", 0.1)
                     gmsh.option.setNumber("Mesh.CharacteristicLengthFactor", 2)  
                     #// Увеличение размера элементов (меньше элементов → меньше файл)
                     gmsh.option.setNumber("Mesh.Binary", 1) 

            # Generate 2D mesh
            #  gmsh.model.mesh.generate(2)
                        
#// Соотношение сторон элементов (меньше = более равносторонние)
                     gmsh.model.mesh.QuadTriangularMaxRatio = 1.5;

#// Сглаживание сетки после генерации
                     # // Алгоритм рекомбинации (0 = Blending)
                     gmsh.model.mesh.RecombinationAlgorithm = 0;
                     gmsh.model.mesh.RecombineAll=1 
                    
           
                     gmsh.model.mesh.generate(2)
            
                     gmsh.model.mesh.Smoothing = 1;
            
            # Save as STL
                     gmsh.write(output_file)
              
                     print(f" -> Succes: {files1}")
            
                  except Exception as e:
                     print(f" -> ERROR: {e}")
                     gmsh.finalize
                     print("--- FINISHED ---")
 

if __name__ == "__main__":
    scan_directory(INPUT_PATH)

