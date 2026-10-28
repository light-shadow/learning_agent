document.querySelectorAll('[data-quiz]').forEach((quiz) => {
  const answer = quiz.dataset.answer;
  const feedback = quiz.querySelector('.feedback');
  const correct = quiz.dataset.correct;
  const incorrect = quiz.dataset.incorrect;

  quiz.querySelectorAll('button[data-choice]').forEach((button) => {
    button.addEventListener('click', () => {
      const isCorrect = button.dataset.choice === answer;
      feedback.textContent = isCorrect ? correct : incorrect;
      feedback.className = `feedback ${isCorrect ? 'correct' : 'incorrect'}`;
    });
  });
});

