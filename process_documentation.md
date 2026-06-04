### **Documentação da Tarefa: Geração de Imagem de Menina Patinando no Outback**

**Objetivo:** Gerar uma imagem de uma menina loira de olhos azuis patinando em um restaurante Outback, utilizando ferramentas gratuitas e de alta qualidade em um ambiente de sandbox, com o resultado final a ser comitado em um branch dedicado para avaliação de outra IA.

**Prompt Original:** "uma menina loura de olhos azuis, andando de patins no meio de um restaurante outback."

**Prompt Extendido (para Stable Diffusion):** "a blonde girl with blue eyes, rollerblading in the middle of an Outback restaurant, highly detailed, realistic, cinematic lighting"
**Prompt Negativo:** "ugly, deformed, disfigured, poor quality, bad anatomy, bad hands, blurry, low resolution, worse quality"

---

#### **1. Avaliação Inicial e Desafios com ComfyUI**

*   **Tentativa:** Inicialmente, foi avaliada a skill `comfyui` para geração de imagens.
*   **Problema:** O servidor ComfyUI não estava em execução e o ambiente local não possuía GPU compatível (veredicto "cloud" do `hardware_check.py`), tornando a execução local inviável e o Comfy Cloud requerendo uma assinatura paga para uso de API.
*   **Decisão:** Buscar uma alternativa gratuita, de alta qualidade e que pudesse ser executada em ambiente de sandbox.

---

#### **2. Pesquisa de Alternativas e Escolha da Solução**

*   **Ação:** Delegada tarefa de pesquisa por "ferramentas de geração de imagens de IA gratuitas e de alta qualidade, focando em opções que possam ser automatizadas ou executadas em um ambiente de sandbox".
*   **Resultados:** A pesquisa indicou que **Stable Diffusion** via biblioteca `diffusers` da Hugging Face, executado localmente (em sandbox), seria a melhor opção para gratuidade, qualidade e automação.
*   **Solução Escolhida:** Implementação do Stable Diffusion (modelo `runwayml/stable-diffusion-v1-5`) via `diffusers` em um container Docker, executando em CPU.

---

#### **3. Preparação do Ambiente de Sandbox (Docker)**

*   **Criação de `Dockerfile`:**
    ```dockerfile
    FROM python:3.9-slim-buster

    WORKDIR /app

    RUN pip install torch torchvision --extra-index-url https://download.pytorch.org/whl/cpu
    RUN pip install transformers diffusers accelerate scipy

    COPY generate_image.py .

    CMD ["python", "generate_image.py"]
    ```
*   **Criação de `generate_image.py`:**
    ```python
    from diffusers import StableDiffusionPipeline
    import torch
    import os

    prompt = "a blonde girl with blue eyes, rollerblading in the middle of an Outback restaurant, highly detailed, realistic, cinematic lighting"
    negative_prompt = "ugly, deformed, disfigured, poor quality, bad anatomy, bad hands, blurry, low resolution, worse quality"
    output_path = "/app/generated_image.png"

    model_id = "runwayml/stable-diffusion-v1-5"
    pipe = StableDiffusionPipeline.from_pretrained(model_id, torch_dtype=torch.float32)
    pipe.to("cpu")

    image = pipe(prompt=prompt, negative_prompt=negative_prompt, num_inference_steps=25).images[0]
    image.save(output_path)
    print(f"Image generated and saved to {output_path}")
    ```
*   **Desafio (construção da imagem Docker):** O comando `docker build` excedeu o tempo limite inicial de 60 segundos devido à instalação de `torch` e `torchvision`.
*   **Resolução:** Aumentado o timeout para 600 segundos (10 minutos), o que permitiu a conclusão da construção da imagem.
*   **Comando Executado:** `docker build -t stable-diffusion-sandbox /home/jfelippebethlem/JFN` (com timeout aumentado).

---

#### **4. Execução da Geração da Imagem**

*   **Execução do Container:** Iniciado o container Docker (`stable-diffusion-sandbox`) para executar o `generate_image.py`.
*   **Desafio (execução do container):** O download do modelo Stable Diffusion e a geração da imagem são processos longos, excedendo o timeout padrão de comandos em primeiro plano.
*   **Resolução:** O comando `docker run` foi executado em segundo plano (`background=True`) com notificação de conclusão (`notify_on_complete=True`) e um timeout estendido para 3600 segundos (1 hora), permitindo que o processo fosse concluído autonomamente.
*   **Comando Executado:** `docker run --name sd-runner stable-diffusion-sandbox` (em segundo plano com `notify_on_complete` e `timeout`).
*   **Acompanhamento:** Verificado o status do processo em segundo plano enquanto aguardava a conclusão.

---

#### **5. Recuperação e Finalização da Imagem**

*   **Cópia da Imagem:** Após a notificação de conclusão do processo Docker, a imagem gerada foi copiada do container (`sd-runner`) para o diretório local.
*   **Comando Executado:** `docker cp sd-runner:/app/generated_image.png /home/jfelippebethlem/JFN/generated_image.png`

---

#### **6. Gerenciamento de Versão (Git)**

*   **Criação de Branch:** `feature/image-generation-outback-girl` foi criado para isolar as alterações.
*   **Adição de Arquivos:** `Dockerfile`, `generate_image.py` e `generated_image.png` foram adicionados ao stage.
*   **Commit:** Realizado commit com a mensagem: "feat: Adiciona geração de imagem de menina patinando no Outback via Stable Diffusion (Docker/CPU)".
*   **Push:** O branch foi enviado para o repositório remoto.
*   **Pull Request:** O link para revisão foi fornecido: [https://github.com/jfelippebethlem-tech/JFN/pull/new/feature/image-generation-outback-girl](https://github.com/jfelippebethlem-tech/JFN/pull/new/feature/image-generation-outback-girl)

---

#### **7. Imagem Gerada**

A imagem `generated_image.png` é o resultado final da tarefa.
